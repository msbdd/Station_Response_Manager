import os
import json
import hashlib
import configparser
from math import log10, floor
from typing import Optional, Tuple, Dict, List
from dataclasses import dataclass, asdict
from obspy import read_inventory
from obspy.core.inventory.response import Response

HASH_SIG_FIGS = 5


def round_to_sig_figs(x: float, sig: int = HASH_SIG_FIGS) -> float:

    if x == 0:
        return 0.0
    return round(x, sig - int(floor(log10(abs(x)))) - 1)


@dataclass
class InstrumentInfo:
    manufacturer: str
    model: str
    description: str
    nrl_path: str
    stage0_gain: Optional[float] = None
    adc_gain: Optional[float] = None
    family_name: Optional[str] = None
    variant_params: Optional[str] = None


def extract_family_info(manufacturer: str, model: str, description: str
                        ) -> Tuple[str, str]:

    import re

    param_patterns = [
        (r'_SG[\d.]+', 'Sensitivity'),
        (r'SG[\d.]+', 'Sensitivity'),
        (r'_PG\d+', 'Preamp Gain'),
        (r'PG\d+', 'Preamp Gain'),
        (r'_LP[\d.]+', 'LP Corner'),
        (r'LP[\d.]+', 'LP Corner'),
        (r'_FV[\d.]+Vpp', 'Full-scale'),
        (r'FV[\d.]+Vpp', 'Full-scale'),
        (r'_FR\d+', 'Sample Rate'),
        (r'FR\d+', 'Sample Rate'),
        (r'_DF[\d.]+', 'DC Filter'),
        (r'DF[\d.]+', 'DC Filter'),
        (r'_FP\w+', 'Phase'),
        (r'FP\w+', 'Phase'),
        (r'_EG\d+', 'Gen'),
        (r'EG\d+', 'Gen'),
        (r'_STground\w+', None),
        (r'STground\w+', None),
        (r'_RC\d+', 'Coil R'),
        (r'RC\d+', 'Coil R'),
        (r'_RS\w+', 'Shunt R'),
        (r'RS\w+', 'Shunt R'),
        (r'_LF[\d.]+', 'LF Corner'),
        (r'LF[\d.]+', 'LF Corner'),
    ]

    base_model = model
    variant_parts = []

    for pattern, param_name in param_patterns:
        matches = re.findall(pattern, base_model)
        for match in matches:
            if param_name:
                value_match = re.search(r'[\d.]+(?:Vpp)?(?:\w+)?$', match)
                if value_match:
                    value = value_match.group()
                    if param_name == 'Sensitivity':
                        variant_parts.append(f"{value} V/m/s")
                    elif param_name == 'Sample Rate':
                        variant_parts.append(f"{value} Hz")
                    elif param_name == 'LP Corner':
                        variant_parts.append(f"LP {value}s")
                    elif param_name == 'Full-scale':
                        variant_parts.append(f"{value}")
                    elif param_name == 'Preamp Gain':
                        variant_parts.append(f"Gain {value}x")
                    elif param_name in ('Gen', 'Phase'):
                        variant_parts.append(match.lstrip('_'))
                    else:
                        variant_parts.append(f"{param_name}: {value}")
            base_model = base_model.replace(match, '', 1)

    base_model = re.sub(r'_+', '_', base_model).strip('_')

    if len(base_model) < 3:
        desc_parts = description.split(';')
        if len(desc_parts) >= 2:
            base_model = desc_parts[1].strip()

    if base_model:
        family_name = f"{manufacturer} {base_model}"
    else:
        family_name = manufacturer

    variant_params = ", ".join(variant_parts) if variant_parts else None

    return family_name, variant_params


@dataclass
class DetectionResult:
    sensor: Optional[InstrumentInfo] = None
    datalogger: Optional[InstrumentInfo] = None
    sensor_candidates: Optional[List['InstrumentInfo']] = None
    datalogger_candidates: Optional[List['InstrumentInfo']] = None
    sensor_confidence: float = 0.0
    datalogger_confidence: float = 0.0

    @property
    def found_any(self) -> bool:
        return self.sensor is not None or self.datalogger is not None

    @property
    def sensor_ambiguous(self) -> bool:
        return (self.sensor_candidates is not None and
                len(self.sensor_candidates) > 1)

    @property
    def datalogger_ambiguous(self) -> bool:
        return (self.datalogger_candidates is not None and
                len(self.datalogger_candidates) > 1)

    @property
    def sensor_family(self) -> Optional[str]:
        if self.sensor and self.sensor.family_name:
            return self.sensor.family_name
        return None

    @property
    def datalogger_family(self) -> Optional[str]:
        if self.datalogger and self.datalogger.family_name:
            return self.datalogger.family_name
        return None


class NRLIndex:

    INDEX_VERSION = "0.1"
    INDEX_FILENAME = os.path.join("resources", "nrl_response_index.json")

    def __init__(self, nrl_root: str, index_dir: str = None):
        self.nrl_root = os.path.normpath(nrl_root)
        self.index_dir = index_dir or os.path.dirname(
            os.path.dirname(__file__))
        self.index_path = os.path.join(self.index_dir, self.INDEX_FILENAME)

        self._index: Optional[Dict] = None
        self._sensor_signatures: Dict[str, List[InstrumentInfo]] = {}
        self._datalogger_signatures: Dict[str, List[InstrumentInfo]] = {}
        self._datalogger_family_sigs: Dict[str, List[InstrumentInfo]] = {}

    @property
    def is_loaded(self) -> bool:
        return self._index is not None

    def get_nrl_modification_hash(self) -> str:
        hasher = hashlib.md5()
        for root, dirs, files in os.walk(self.nrl_root):
            dirs.sort()
            files.sort()
            for fname in files:
                if fname.endswith(('.xml', '.txt')):
                    fpath = os.path.join(root, fname)
                    rel_path = os.path.relpath(fpath, self.nrl_root)
                    mtime = os.path.getmtime(fpath)
                    hasher.update(f"{rel_path}:{mtime}".encode())
        return hasher.hexdigest()

    def needs_rebuild(self) -> bool:
        if not os.path.exists(self.index_path):
            return True
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get('version') != self.INDEX_VERSION:
                return True
            stored_hash = data.get('nrl_hash', '')
            current_hash = self.get_nrl_modification_hash()
            return stored_hash != current_hash
        except (json.JSONDecodeError, IOError):
            return True

    def load_index(self) -> bool:
        if not os.path.exists(self.index_path):
            return False
        try:
            with open(self.index_path, 'r', encoding='utf-8') as f:
                self._index = json.load(f)

            self._sensor_signatures = {}
            for sig, info_data in self._index.get('sensors', {}).items():
                if isinstance(info_data, list):
                    self._sensor_signatures[sig] = [
                        InstrumentInfo(**info) for info in info_data
                    ]
                else:
                    self._sensor_signatures[sig] = [
                        InstrumentInfo(**info_data)
                    ]

            self._datalogger_signatures = {}
            for sig, info_list in self._index.get('dataloggers', {}).items():
                self._datalogger_signatures[sig] = [
                    InstrumentInfo(**info) for info in info_list
                ]

            self._datalogger_family_sigs = {}
            dl_family = self._index.get('dataloggers_family', {})
            for sig, info_list in dl_family.items():
                if isinstance(info_list, list):
                    self._datalogger_family_sigs[sig] = [
                        InstrumentInfo(**info) for info in info_list
                    ]
                else:
                    self._datalogger_family_sigs[sig] = [
                        InstrumentInfo(**info_list)
                    ]

            return True
        except (json.JSONDecodeError, IOError, KeyError) as e:
            print(f"Error loading NRL index: {e}")
            return False

    def save_index(self) -> bool:
        try:
            data = {
                'version': self.INDEX_VERSION,
                'nrl_hash': self.get_nrl_modification_hash(),
                'sensors': {
                    sig: [asdict(info) for info in info_list]
                    for sig, info_list in self._sensor_signatures.items()
                },
                'dataloggers': {
                    sig: [asdict(info) for info in info_list]
                    for sig, info_list in self._datalogger_signatures.items()
                },
                'dataloggers_family': {
                    sig: [asdict(info) for info in info_list]
                    for sig, info_list in self._datalogger_family_sigs.items()
                }
            }
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            self._index = data
            return True
        except IOError as e:
            print(f"Error saving NRL index: {e}")
            return False

    def build_index(self, progress_callback=None) -> Tuple[int, int]:
        self._sensor_signatures = {}
        self._datalogger_signatures = {}
        self._datalogger_family_sigs = {}

        sensor_dir = os.path.join(self.nrl_root, 'sensor')
        datalogger_dir = os.path.join(self.nrl_root, 'datalogger')

        if progress_callback:
            progress_callback(0, 0, "Scanning sensor directory...")

        sensor_files = self._collect_xml_files(sensor_dir)

        if progress_callback:
            msg = f"Found {len(sensor_files)} sensors. Scanning dataloggers..."
            progress_callback(0, 0, msg)

        datalogger_files = self._collect_xml_files(datalogger_dir)

        total_files = len(sensor_files) + len(datalogger_files)
        current = 0

        if progress_callback:
            msg = f"Indexing {total_files} files..."
            progress_callback(0, total_files, msg)

        for xml_path, info in sensor_files:
            current += 1
            if progress_callback:
                progress_callback(current, total_files,
                                  f"Sensor: {info['model']}")
            try:
                sig, stage0_gain = self._compute_sensor_info_from_file(
                    xml_path
                )
                if sig:
                    family_name, variant_params = extract_family_info(
                        info['manufacturer'],
                        info['model'],
                        info['description']
                    )
                    instrument = InstrumentInfo(
                        manufacturer=info['manufacturer'],
                        model=info['model'],
                        description=info['description'],
                        nrl_path=os.path.relpath(xml_path, self.nrl_root),
                        stage0_gain=stage0_gain,
                        family_name=family_name,
                        variant_params=variant_params
                    )
                    if sig not in self._sensor_signatures:
                        self._sensor_signatures[sig] = []
                    self._sensor_signatures[sig].append(instrument)
            except Exception as e:
                print(f"Error indexing sensor {xml_path}: {e}")

        for xml_path, info in datalogger_files:
            current += 1
            if progress_callback:
                progress_callback(current, total_files,
                                  f"Datalogger: {info['model']}")
            try:
                dl_info = self._compute_datalogger_info_from_file(xml_path)
                exact_sig = dl_info[0]  # With gain
                family_sig = dl_info[3]  # Without gain
                if exact_sig:
                    family_name, variant_params = extract_family_info(
                        info['manufacturer'],
                        info['model'],
                        info['description']
                    )
                    instrument = InstrumentInfo(
                        manufacturer=info['manufacturer'],
                        model=info['model'],
                        description=info['description'],
                        nrl_path=os.path.relpath(xml_path, self.nrl_root),
                        stage0_gain=dl_info[1],
                        adc_gain=dl_info[2],
                        family_name=family_name,
                        variant_params=variant_params
                    )
                    if exact_sig not in self._datalogger_signatures:
                        self._datalogger_signatures[exact_sig] = []
                    self._datalogger_signatures[exact_sig].append(instrument)

                    if family_sig:
                        if family_sig not in self._datalogger_family_sigs:
                            self._datalogger_family_sigs[family_sig] = []
                        self._datalogger_family_sigs[family_sig].append(
                            instrument
                        )
            except Exception as e:
                print(f"Error indexing datalogger {xml_path}: {e}")

        if progress_callback:
            progress_callback(total_files, total_files, "Saving index...")

        self.save_index()

        return len(self._sensor_signatures), len(self._datalogger_signatures)

    def _collect_xml_files(self, base_dir: str) -> List[Tuple[str, Dict]]:
        """Collect all XML files with their metadata."""
        files = []
        if not os.path.exists(base_dir):
            return files

        txt_cache = self._build_txt_cache(base_dir)

        for manufacturer_dir in sorted(os.listdir(base_dir)):
            manufacturer_path = os.path.join(base_dir, manufacturer_dir)
            if not os.path.isdir(manufacturer_path):
                continue
            if manufacturer_dir == 'index.txt':
                continue
            files.extend(
                self._collect_manufacturer_files(
                    manufacturer_path, manufacturer_dir, txt_cache
                )
            )
        return files

    def _build_txt_cache(self, base_dir: str) -> Dict[str, Dict[str, str]]:
        cache = {}
        for root, dirs, filenames in os.walk(base_dir):
            dir_cache = {}
            for fname in filenames:
                if not fname.endswith('.txt'):
                    continue
                txt_path = os.path.join(root, fname)
                try:
                    config = configparser.ConfigParser()
                    config.optionxform = str
                    config.read(txt_path, encoding='utf-8-sig')
                    for section in config.sections():
                        if section == 'Main':
                            continue
                        xml_ref = config.get(
                            section, 'xml', fallback=''
                        ).strip().strip('"')
                        if xml_ref:
                            xml_fname = os.path.basename(xml_ref)
                            desc = config.get(
                                section, 'description', fallback=''
                            ).strip().strip('"')
                            if desc:
                                dir_cache[xml_fname] = f"{section}: {desc}"
                            else:
                                dir_cache[xml_fname] = section
                except Exception:
                    continue
            if dir_cache:
                cache[root] = dir_cache
        return cache

    def _collect_manufacturer_files(
        self, mfr_path: str, manufacturer: str,
        txt_cache: Dict[str, Dict[str, str]]
    ) -> List[Tuple[str, Dict]]:
        files = []
        for root, dirs, filenames in os.walk(mfr_path):
            rel_path = os.path.relpath(root, mfr_path)
            model_parts = rel_path.split(os.sep) if rel_path != '.' else []
            dir_descriptions = txt_cache.get(root, {})

            for fname in filenames:
                if not fname.endswith('.xml'):
                    continue
                xml_path = os.path.join(root, fname)
                if model_parts:
                    model = ' / '.join(model_parts)
                else:
                    model = os.path.splitext(fname)[0]
                description = dir_descriptions.get(fname, fname)
                files.append((xml_path, {
                    'manufacturer': manufacturer,
                    'model': model,
                    'description': description
                }))
        return files

    def _compute_sensor_info_from_file(
        self, xml_path: str
    ) -> Tuple[Optional[str], Optional[float]]:
        try:
            inv = read_inventory(xml_path)
            if inv and inv[0] and inv[0][0] and inv[0][0][0]:
                response = inv[0][0][0].response
                sig = self._compute_sensor_signature(response)

                stage0_gain = None
                if response.response_stages:
                    stage0 = response.response_stages[0]
                    if hasattr(stage0, 'stage_gain') and stage0.stage_gain:
                        stage0_gain = float(stage0.stage_gain)

                return sig, stage0_gain
        except Exception as e:
            print(f"Could not read sensor {xml_path}: {e}")
        return None, None

    def _compute_datalogger_info_from_file(
        self, xml_path: str
    ) -> Tuple[Optional[str], Optional[float], Optional[float], Optional[str]]:
        try:
            inv = read_inventory(xml_path)
            if inv and inv[0] and inv[0][0] and inv[0][0][0]:
                response = inv[0][0][0].response

                adc_idx = self._find_adc_stage_index(response)
                if adc_idx is not None:
                    exact_sig = self._compute_dl_sig_with_preamp(
                        response, adc_idx
                    )
                    family_sig = self._compute_dl_sig_without_gain(
                        response, adc_idx
                    )
                else:
                    fn = self._compute_datalogger_signature_stages_1_plus
                    exact_sig = fn(response)
                    family_sig = exact_sig
                    adc_idx = 1

                stage0_gain = None
                if response.response_stages:
                    stage0 = response.response_stages[0]
                    if hasattr(stage0, 'stage_gain') and stage0.stage_gain:
                        stage0_gain = float(stage0.stage_gain)

                adc_gain = None
                if adc_idx is not None:
                    adc_gain = self._compute_total_digital_gain(
                        response, adc_idx
                    )

                return exact_sig, stage0_gain, adc_gain, family_sig
        except Exception as e:
            print(f"Could not read datalogger {xml_path}: {e}")
        return None, None, None, None

    def _compute_dl_sig_with_preamp(
        self, response: Response, adc_idx: int
    ) -> Optional[str]:
        if not response or not response.response_stages:
            return None
        if adc_idx >= len(response.response_stages):
            return None

        hasher = hashlib.sha256()
        hasher.update(b"dl_exact:")

        if response.response_stages[0]:
            preamp_gain = getattr(
                response.response_stages[0], 'stage_gain', None
            )
            if preamp_gain:
                hasher.update(f":pg={round(preamp_gain, 2)}".encode())

        total_gain = self._compute_total_digital_gain(response, adc_idx)
        hasher.update(f":tg={round(total_gain, 2)}".encode())

        fir_idx = 0
        for stage in response.response_stages[adc_idx:]:
            if self._is_passthrough_stage(stage):
                continue
            coeffs = self._get_fir_coefficients(stage)
            if coeffs:
                self._hash_fir_fingerprint(coeffs, hasher, f"f{fir_idx}")
                dec = getattr(stage, 'decimation_factor', None)
                if dec:
                    hasher.update(f":dec={dec}".encode())
                fir_idx += 1

        return hasher.hexdigest()

    def _compute_sensor_signature(self, response: Response) -> Optional[str]:

        if not response or not response.response_stages:
            return None

        stage = response.response_stages[0]
        return self._hash_stage(stage, prefix="sensor")

    def _compute_datalogger_signature_stages_1_plus(
        self, response: Response
    ) -> Optional[str]:

        if not response or not response.response_stages:
            return None
        if len(response.response_stages) < 2:
            return None

        hasher = hashlib.sha256()
        hasher.update(b"datalogger:")

        for i, stage in enumerate(response.response_stages[1:]):
            stage_hash = self._hash_stage(stage, prefix=f"s{i}")
            if stage_hash:
                hasher.update(stage_hash.encode())

        return hasher.hexdigest()

    def _hash_stage(
        self, stage, prefix: str = "", exclude_gain: bool = False,
        normalize_type: bool = False
    ) -> Optional[str]:

        hasher = hashlib.sha256()
        stage_type = type(stage).__name__

        if (
            normalize_type
            and ('FIR' in stage_type or 'Coefficients' in stage_type)
        ):
            hasher.update(f"{prefix}:DigitalFilter".encode())
        else:
            hasher.update(f"{prefix}:{stage_type}".encode())

        if not exclude_gain:
            if hasattr(stage, 'stage_gain') and stage.stage_gain:
                gain = round(float(stage.stage_gain), 2)
                hasher.update(f":gain={gain}".encode())

        if hasattr(stage, 'decimation_factor') and stage.decimation_factor:
            hasher.update(f":dec={stage.decimation_factor}".encode())

        if 'PolesZeros' in stage_type:
            if hasattr(stage, 'pz_transfer_function_type'):
                hasher.update(
                    f":tf={stage.pz_transfer_function_type}".encode())

            if hasattr(stage, 'poles') and stage.poles:
                poles = sorted(
                    stage.poles,
                    key=lambda x: (round_to_sig_figs(x.real),
                                   round_to_sig_figs(x.imag))
                )
                for p in poles:
                    pr = round_to_sig_figs(p.real)
                    pi = round_to_sig_figs(p.imag)
                    hasher.update(f":p={pr},{pi}".encode())

            if hasattr(stage, 'zeros') and stage.zeros:
                zeros = sorted(
                    stage.zeros,
                    key=lambda x: (round_to_sig_figs(x.real),
                                   round_to_sig_figs(x.imag))
                )
                for z in zeros:
                    zr = round_to_sig_figs(z.real)
                    zi = round_to_sig_figs(z.imag)
                    hasher.update(f":z={zr},{zi}".encode())

        if 'FIR' in stage_type or 'Coefficients' in stage_type:
            if hasattr(stage, 'symmetry') and stage.symmetry:
                hasher.update(f":sym={stage.symmetry}".encode())

            coeffs = None
            if hasattr(stage, 'numerator') and stage.numerator:
                coeffs = stage.numerator
            elif hasattr(stage, 'coefficients') and stage.coefficients:
                coeffs = stage.coefficients

            if coeffs:
                hasher.update(f":nc={len(coeffs)}".encode())
                for c in coeffs:
                    cv = round_to_sig_figs(float(c))
                    hasher.update(f":{cv}".encode())

        return hasher.hexdigest()

    def detect_instrument(self, response: Response) -> DetectionResult:

        if not self.is_loaded:
            if not self.load_index():
                return DetectionResult()

        result = DetectionResult()

        sensor_sig = self._compute_sensor_signature(response)
        if sensor_sig and sensor_sig in self._sensor_signatures:
            candidates = self._sensor_signatures[sensor_sig]
            result.sensor_candidates = candidates

            if len(candidates) == 1:
                result.sensor = candidates[0]
                result.sensor_confidence = 1.0
            else:
                result.sensor = candidates[0]
                result.sensor_confidence = 0.0

        adc_idx = self._find_adc_stage_index(response)
        if adc_idx is not None:
            user_preamp_gain = self._find_preamp_gain(response, adc_idx)
            exact_sig = self._compute_dl_sig_with_user_preamp(
                response, adc_idx, user_preamp_gain
            )
            if exact_sig and exact_sig in self._datalogger_signatures:
                candidates = self._datalogger_signatures[exact_sig]
                result.datalogger_candidates = candidates

                if len(candidates) == 1:
                    result.datalogger = candidates[0]
                    result.datalogger_confidence = 1.0
                else:
                    result.datalogger = candidates[0]
                    result.datalogger_confidence = 0.0
                return result

        family_sig = self._compute_datalogger_signature_from_response(response)
        if family_sig and family_sig in self._datalogger_family_sigs:
            candidates = self._datalogger_family_sigs[family_sig]
            result.datalogger_candidates = candidates

            if len(candidates) == 1:
                result.datalogger = candidates[0]
                result.datalogger_confidence = 1.0
            elif len(candidates) > 1:
                best_match = self._disambiguate_by_gain_calculation(
                    response, candidates, result.sensor, adc_idx
                )
                if best_match:
                    result.datalogger = best_match[0]
                    result.datalogger_confidence = best_match[1]
                else:
                    result.datalogger = candidates[0]
                    result.datalogger_confidence = 0.0

        return result

    def _find_adc_stage_index(self, response: Response) -> Optional[int]:
        if not response or not response.response_stages:
            return None

        for i, stage in enumerate(response.response_stages):
            in_units = getattr(stage, 'input_units', None)
            out_units = getattr(stage, 'output_units', None)

            in_str = str(in_units).upper() if in_units else ""
            out_str = str(out_units).upper() if out_units else ""

            is_volt_in = in_str in ('V', 'VOLT', 'VOLTS')
            is_count_out = 'COUNT' in out_str

            if is_volt_in and is_count_out:
                return i

        return None

    def _find_preamp_gain(
        self, response: Response, adc_idx: int
    ) -> Optional[float]:
        if not response or adc_idx is None or adc_idx <= 1:
            return None

        preamp_gain = 1.0
        found_preamp = False

        for i in range(1, adc_idx):
            stage = response.response_stages[i]
            in_u = str(getattr(stage, 'input_units', '')).upper()
            out_u = str(getattr(stage, 'output_units', '')).upper()

            is_v_to_v = (in_u in ('V', 'VOLT', 'VOLTS') and
                         out_u in ('V', 'VOLT', 'VOLTS'))

            if is_v_to_v:
                gain = getattr(stage, 'stage_gain', 1.0) or 1.0
                preamp_gain *= float(gain)
                found_preamp = True

        return preamp_gain if found_preamp else None

    def _compute_dl_sig_with_user_preamp(
        self, response: Response, adc_idx: int,
        user_preamp_gain: Optional[float]
    ) -> Optional[str]:

        if not response or not response.response_stages:
            return None
        if adc_idx >= len(response.response_stages):
            return None

        hasher = hashlib.sha256()
        hasher.update(b"dl_exact:")

        if user_preamp_gain is not None:
            hasher.update(f":pg={round(user_preamp_gain, 2)}".encode())

        total_gain = self._compute_total_digital_gain(response, adc_idx)
        hasher.update(f":tg={round(total_gain, 2)}".encode())

        fir_idx = 0
        for stage in response.response_stages[adc_idx:]:
            if self._is_passthrough_stage(stage):
                continue
            coeffs = self._get_fir_coefficients(stage)
            if coeffs:
                self._hash_fir_fingerprint(coeffs, hasher, f"f{fir_idx}")
                dec = getattr(stage, 'decimation_factor', None)
                if dec:
                    hasher.update(f":dec={dec}".encode())
                fir_idx += 1

        return hasher.hexdigest()

    def _compute_datalogger_signature_from_response(
        self, response: Response
    ) -> Optional[str]:
        if not response or not response.response_stages:
            return None

        adc_idx = self._find_adc_stage_index(response)

        if adc_idx is not None:
            return self._compute_dl_sig_without_gain(response, adc_idx)

        return None

    def _compute_total_digital_gain(
        self, response: Response, adc_idx: int
    ) -> float:
        total = 1.0
        for stage in response.response_stages[adc_idx:]:
            gain = getattr(stage, 'stage_gain', 1.0)
            if gain:
                total *= float(gain)
        return total

    def _get_fir_coefficients(self, stage) -> Optional[list]:
        coeffs = None
        if hasattr(stage, 'numerator') and stage.numerator:
            coeffs = list(stage.numerator)
        elif hasattr(stage, 'coefficients') and stage.coefficients:
            coeffs = list(stage.coefficients)
        return coeffs

    def _is_passthrough_stage(self, stage) -> bool:
        coeffs = self._get_fir_coefficients(stage)
        if coeffs is None or len(coeffs) == 0:
            return True
        if len(coeffs) == 1 and abs(coeffs[0] - 1.0) < 0.001:
            return True
        return False

    def _hash_fir_fingerprint(
        self, coeffs: list, hasher, prefix: str
    ) -> None:
        n = len(coeffs)
        hasher.update(f"{prefix}:n={n}".encode())
        for i in range(min(3, n)):
            cv = round_to_sig_figs(float(coeffs[i]))
            hasher.update(f":c{i}={cv}".encode())
        for i in range(max(0, n - 3), n):
            cv = round_to_sig_figs(float(coeffs[i]))
            hasher.update(f":c{i}={cv}".encode())
        coeff_sum = sum(float(c) for c in coeffs)
        hasher.update(f":sum={round_to_sig_figs(coeff_sum)}".encode())

    def _compute_dl_sig_without_gain(
        self, response: Response, adc_idx: int
    ) -> Optional[str]:

        if not response or not response.response_stages:
            return None
        if adc_idx >= len(response.response_stages):
            return None

        hasher = hashlib.sha256()
        hasher.update(b"dl_family:")

        fir_idx = 0
        for stage in response.response_stages[adc_idx:]:
            if self._is_passthrough_stage(stage):
                continue
            coeffs = self._get_fir_coefficients(stage)
            if coeffs:
                self._hash_fir_fingerprint(coeffs, hasher, f"f{fir_idx}")
                dec = getattr(stage, 'decimation_factor', None)
                if dec:
                    hasher.update(f":dec={dec}".encode())
                fir_idx += 1

        return hasher.hexdigest()

    def _disambiguate_by_gain_calculation(
        self,
        response: Response,
        candidates: List[InstrumentInfo],
        sensor: Optional[InstrumentInfo] = None,
        adc_idx: Optional[int] = None
    ) -> Optional[Tuple[InstrumentInfo, float]]:

        if adc_idx is None:
            adc_idx = self._find_adc_stage_index(response)
        if adc_idx is None:
            return None

        user_adc_gain = self._compute_total_digital_gain(response, adc_idx)

        if user_adc_gain is None or user_adc_gain == 0:
            return None

        user_preamp_gain = 1.0
        for i in range(1, adc_idx):
            stage = response.response_stages[i]
            if hasattr(stage, 'stage_gain') and stage.stage_gain:
                user_preamp_gain *= abs(float(stage.stage_gain))

        if user_preamp_gain == 0:
            return None

        tolerance = 0.15
        matches = []

        for candidate in candidates:
            if candidate.adc_gain and candidate.stage0_gain:
                candidate_adc = abs(candidate.adc_gain)
                candidate_preamp = abs(candidate.stage0_gain)

                if candidate_adc > 0 and candidate_preamp > 0:
                    adc_ratio = user_adc_gain / candidate_adc
                    preamp_ratio = candidate_preamp / user_preamp_gain

                    if preamp_ratio > 0:
                        rel_diff = abs(adc_ratio - preamp_ratio) / preamp_ratio
                        if rel_diff < tolerance:
                            conf = max(0.5, 1.0 - rel_diff * 2)
                            matches.append((candidate, conf))

        if matches:
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[0]

        for candidate in candidates:
            if candidate.adc_gain:
                candidate_adc = abs(candidate.adc_gain)
                if candidate_adc > 0:
                    ratio = user_adc_gain / candidate_adc
                    for expected in [1.0, 2.0, 4.0, 0.5, 0.25]:
                        rel_diff = abs(ratio - expected) / expected
                        if rel_diff < 0.1:
                            conf = 0.7 - rel_diff
                            matches.append((candidate, conf))
                            break

        if matches:
            matches.sort(key=lambda x: x[1], reverse=True)
            return matches[0]

        return None

    def format_detection_result(
        self, result: DetectionResult, multiline: bool = False,
        show_family: bool = True
    ) -> str:
        parts = []

        if result.sensor:
            if show_family and result.sensor_ambiguous:
                n_similar = len(result.sensor_candidates) - 1
                family = result.sensor.family_name or result.sensor.model
                parts.append(f"Sensor: {family} (+{n_similar} similar)")
            else:
                mfr = result.sensor.manufacturer
                model = result.sensor.model
                parts.append(f"Sensor: {mfr} {model}")

        if result.datalogger:
            if show_family and result.datalogger_ambiguous:
                n_similar = len(result.datalogger_candidates) - 1
                family = (result.datalogger.family_name or
                          result.datalogger.model)
                parts.append(f"Datalogger: {family} (+{n_similar} similar)")
            else:
                mfr = result.datalogger.manufacturer
                model = result.datalogger.model
                parts.append(f"Datalogger: {mfr} {model}")

        if not parts:
            return ""

        separator = "\n" if multiline else " | "
        return separator.join(parts)

    def get_stats(self) -> Dict[str, int]:
        """Get index statistics."""
        return {
            'sensors': len(self._sensor_signatures),
            'dataloggers': len(self._datalogger_signatures)
        }
