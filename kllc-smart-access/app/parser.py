import xml.etree.ElementTree as ET
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any, Tuple
from app.config import CAMERA_CHANNELS

def clean_tag(tag: str) -> str:
    """Strip XML namespace prefix if present."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag

def normalize_channel_id(raw_ch: Any) -> int:
    """Normalize Hikvision channel IDs like 101, 201, 301, 901 or 'D2' to integer 1, 2, 3, 9."""
    if raw_ch is None:
        return 1
    s = str(raw_ch).strip().upper()
    if s.startswith("D"):
        digits = re.findall(r"\d+", s)
        if digits:
            return int(digits[0])
    try:
        val = int(s)
        # NVR IP Camera proxy channels often start at 101, 201, 301, etc.
        if val > 100 and val % 100 == 1:
            return val // 100
        return val
    except ValueError:
        return 1

def parse_xml_tree(xml_content: str) -> Optional[ET.Element]:
    """Clean namespaces and parse XML string into ElementTree Root."""
    try:
        xml_content = xml_content.strip()
        if not xml_content.startswith("<"):
            first_bracket = xml_content.find("<")
            if first_bracket != -1:
                xml_content = xml_content[first_bracket:]
            else:
                return None
        xml_content = re.sub(r'\s+xmlns(?::\w+)?="[^"]+"', '', xml_content)
        return ET.fromstring(xml_content)
    except Exception:
        return None

def find_first(node: Optional[ET.Element], *xpaths: str) -> Optional[ET.Element]:
    """Find first matching element among given xpaths, safely checking 'is not None'."""
    if node is None:
        return None
    for xpath in xpaths:
        el = node.find(xpath)
        if el is not None:
            return el
    return None

def find_first_text(node: Optional[ET.Element], *xpaths: str) -> Optional[str]:
    """Find first matching text among given xpaths."""
    el = find_first(node, *xpaths)
    if el is not None and el.text:
        return el.text.strip()
    return None

def parse_alert_xml(xml_content: str) -> Optional[Dict[str, Any]]:
    """Parse Hikvision XML Alert notification into standardized access event dict."""
    try:
        root = parse_xml_tree(xml_content)
        if root is None:
            return None
        root_tag = clean_tag(root.tag).lower()

        # Find event type
        event_type = find_first_text(root, ".//eventType") or root_tag

        # Find event time
        raw_time = find_first_text(root, ".//dateTime")
        event_time_str = ""
        if raw_time:
            try:
                dt = datetime.fromisoformat(raw_time)
                event_time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                event_time_str = raw_time.replace("T", " ").split("+")[0].split(".")[0]
        else:
            event_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Find Channel ID
        raw_ch = find_first_text(root, ".//channelID", ".//dynChannelID", ".//channelNumber")
        channel_id = normalize_channel_id(raw_ch) if raw_ch else 1

        cam_config = CAMERA_CHANNELS.get(channel_id, {})
        camera_name = cam_config.get("name", f"Camera D{channel_id}")

        # Check for Face Match details
        match_el = find_first(root, ".//FaceMatch", ".//match", ".//FaceMatchInfo")
        is_face_event = any(k in event_type.lower() for k in ["face", "snap", "facematch", "facesnapmatch"])

        if match_el is not None:
            match_status = "MATCHED"

            # Check inside personInfo sub-element first, then match_el
            person_info_el = find_first(match_el, ".//personInfo", ".//PersonInfo")
            target_person_el = person_info_el if person_info_el is not None else match_el

            person_code = find_first_text(target_person_el, ".//customInfo", ".//personCode", ".//employeeNo")
            full_name = find_first_text(target_person_el, ".//name", ".//personName")

            # If person_code not set, attempt to extract from name (e.g. 130009_Yupin Lo)
            if not person_code and full_name and "_" in full_name:
                parts = full_name.split("_", 1)
                if parts[0].isdigit():
                    person_code = parts[0]

            # Library Name
            fd_lib_node = find_first(match_el, ".//FDLib", ".//FDLibInfo")
            lib_name = find_first_text(fd_lib_node, ".//name") if fd_lib_node is not None else find_first_text(match_el, ".//libName")
            if not lib_name:
                lib_name = "KLLC STAFF"

            # Similarity
            similarity = 0.0
            sim_str = find_first_text(match_el, ".//similarity")
            if sim_str:
                try:
                    val = float(sim_str)
                    similarity = val * 100.0 if val <= 1.0 else val
                    similarity = round(similarity, 1)
                except ValueError:
                    similarity = 0.0

            # Snapshot URL
            snapshot_url = find_first_text(match_el, ".//pictureURL", ".//snapURL") or find_first_text(root, ".//pictureURL", ".//snapURL")

            return {
                "event_type": event_type,
                "event_time": event_time_str,
                "channel_id": channel_id,
                "camera_name": camera_name,
                "match_status": match_status,
                "person_code": person_code or "UNKNOWN",
                "full_name": full_name or "Unknown Person",
                "library_name": lib_name,
                "similarity": similarity,
                "direction": "IN" if channel_id in (2, 3) else "OUT",
                "snapshot_url": snapshot_url
            }

        elif is_face_event:
            # Face detected but not matched (UNKNOWN)
            snapshot_url = find_first_text(root, ".//pictureURL", ".//snapURL", ".//picture")

            return {
                "event_type": event_type,
                "event_time": event_time_str,
                "channel_id": channel_id,
                "camera_name": camera_name,
                "match_status": "UNKNOWN",
                "person_code": None,
                "full_name": None,
                "library_name": None,
                "similarity": 0.0,
                "direction": "IN" if channel_id in (2, 3) else "OUT",
                "snapshot_url": snapshot_url
            }

        # People Counting event
        if "peoplecounting" in event_type.lower():
            enter_str = find_first_text(root, ".//enter", ".//enterNum") or "0"
            exit_str = find_first_text(root, ".//exit", ".//exitNum") or "0"
            return {
                "event_type": "peopleCounting",
                "event_time": event_time_str,
                "channel_id": channel_id,
                "camera_name": camera_name,
                "enter_count": int(enter_str) if enter_str.isdigit() else 0,
                "exit_count": int(exit_str) if exit_str.isdigit() else 0
            }

        return None
    except Exception as e:
        return None

def parse_alert_json(json_content: str) -> Optional[Dict[str, Any]]:
    """Parse Hikvision JSON Alert notification."""
    try:
        data = json.loads(json_content)
        event_type = data.get("eventType", "")
        raw_ch = data.get("channelID", data.get("dynChannelID", 1))
        channel_id = normalize_channel_id(raw_ch)
        cam_config = CAMERA_CHANNELS.get(channel_id, {})
        camera_name = cam_config.get("name", f"Camera D{channel_id}")

        event_time_str = data.get("dateTime", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        if "T" in event_time_str:
            event_time_str = event_time_str.replace("T", " ").split("+")[0].split(".")[0]

        matches = data.get("FaceMatchList", data.get("MatchList", []))
        if matches and len(matches) > 0:
            m = matches[0]
            person_info = m.get("personInfo", {})
            p_code = person_info.get("customInfo", person_info.get("personCode"))
            p_name = person_info.get("name")
            sim_val = float(m.get("similarity", 0.0))
            if sim_val <= 1.0:
                sim_val = sim_val * 100.0

            return {
                "event_type": event_type,
                "event_time": event_time_str,
                "channel_id": channel_id,
                "camera_name": camera_name,
                "match_status": "MATCHED",
                "person_code": p_code,
                "full_name": p_name,
                "library_name": m.get("FDLib", {}).get("name", "KLLC STAFF"),
                "similarity": round(sim_val, 1),
                "direction": "IN" if channel_id in (2, 3) else "OUT",
                "snapshot_url": m.get("pictureURL")
            }
        else:
            return {
                "event_type": event_type,
                "event_time": event_time_str,
                "channel_id": channel_id,
                "camera_name": camera_name,
                "match_status": "UNKNOWN",
                "person_code": None,
                "full_name": None,
                "library_name": None,
                "similarity": 0.0,
                "direction": "IN" if channel_id in (2, 3) else "OUT",
                "snapshot_url": data.get("pictureURL")
            }
    except Exception:
        return None

def parse_alert_payload(raw_text: str) -> Optional[Dict[str, Any]]:
    """Auto-detect format (XML or JSON) and parse payload."""
    raw_text = raw_text.strip()
    if raw_text.startswith("{"):
        return parse_alert_json(raw_text)
    elif "<" in raw_text:
        return parse_alert_xml(raw_text)
    return None
