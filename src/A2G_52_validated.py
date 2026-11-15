#!/usr/bin/env python3
# A2G Parser 12
# Required:
#   pip install requests gns3fy "pydantic<2"

import argparse
import json
import os
import xml.etree.ElementTree as ET
from datetime import datetime

import pydantic
import requests

try:
    from gns3fy import Gns3Connector
except ImportError:
    print("ERROR: gns3fy library not found.")
    print('Install with: pip install requests gns3fy "pydantic<2"')
    raise


# ============================================================
# Configuration
# ============================================================

DEFAULT_GNS3_URL = "http://localhost:3080"
DEFAULT_GNS3_PROJECT_BASE_NAME = "A2G_AutoGen"
DEFAULT_XML_FILENAME = "A2G-52 nodes.xml"

# Save generated GNS3 projects in the same folder as this Python script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ArchiMate view used for node positions
DEFAULT_TARGET_VIEW_NAME = "V1 – Technology Security (GNS3)"

# Never allow generated projects to reuse these important names
PROTECTED_PROJECT_NAMES = {
    "Archimate_Generated_Lab",
    "ArchiMate_Generated_Lab",
    "Archimate_Generated_Lab - GNS3",
    "ArchiMate_Generated_Lab - GNS3",
}

# Mapping layer:
# Keep the ArchiMate XML unchanged and translate its logical/template names
# to the actual template names currently installed in GNS3.
TEMPLATE_ALIASES = {
    "Windows10": "Windows 10",
    "TinyCoreVM": "TinyCore Linux",
}

# Position tuning: ArchiMate -> GNS3
ARCHI_SCALE = 0.70
PADDING = 80
DUPLICATE_NUDGE_X = 80
DUPLICATE_NUDGE_Y = 40

REQUEST_TIMEOUT = 30
CREATE_TIMEOUT = 60


# ============================================================
# Helpers
# ============================================================

def safe_text(el, default=""):
    if el is None or el.text is None:
        return default
    return el.text


def normalize_node_type(raw: str) -> str:
    if not raw:
        return ""
    return raw.strip().lower()


def normalize_positions(nodes, scale=ARCHI_SCALE, padding=PADDING):
    """Normalize ArchiMate coordinates to GNS3-friendly coordinates."""
    if not nodes:
        return nodes

    xs = [n.get("x", 0) for n in nodes]
    ys = [n.get("y", 0) for n in nodes]
    min_x, min_y = min(xs), min(ys)

    for n in nodes:
        n["x"] = int((n.get("x", 0) - min_x) * scale + padding)
        n["y"] = int((n.get("y", 0) - min_y) * scale + padding)

    # Avoid exact overlaps
    used = set()
    for n in nodes:
        while (n["x"], n["y"]) in used:
            n["x"] += DUPLICATE_NUDGE_X
            n["y"] += DUPLICATE_NUDGE_Y
        used.add((n["x"], n["y"]))

    return nodes


def unique_project_name(base_name: str, server: Gns3Connector) -> str:
    """Create a timestamped project name without overwriting an existing one."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = f"{base_name}_{ts}"

    try:
        existing_names = {p.get("name") for p in server.get_projects()}
    except Exception:
        return candidate

    if candidate not in existing_names:
        return candidate

    i = 2
    while True:
        candidate_i = f"{candidate}_{i}"
        if candidate_i not in existing_names:
            return candidate_i
        i += 1


def fetch_gns3_templates(gns3_url: str):
    """
    Return:
      templates: raw template list
      exact_map: exact name -> template
      folded_map: case-insensitive name -> template
    """
    url = f"{gns3_url.rstrip('/')}/v2/templates"
    response = requests.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    templates = response.json()

    exact_map = {}
    folded_map = {}

    for t in templates:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        exact_map[name] = t
        folded_map[name.casefold()] = t

    return templates, exact_map, folded_map


def resolve_template_name(archi_template_name: str, exact_map, folded_map):
    """
    Resolve an ArchiMate gns3_template value to an installed GNS3 template.

    Resolution order:
      1. Exact installed template name
      2. TEMPLATE_ALIASES mapping
      3. Case-insensitive installed template name
      4. Case-insensitive alias lookup
    """
    original = (archi_template_name or "").strip()
    if not original:
        return None, None

    # 1) Exact installed name
    if original in exact_map:
        return original, exact_map[original]

    # 2) Exact alias
    alias = TEMPLATE_ALIASES.get(original)
    if alias:
        if alias in exact_map:
            return alias, exact_map[alias]
        if alias.casefold() in folded_map:
            t = folded_map[alias.casefold()]
            return t["name"], t

    # 3) Case-insensitive installed name
    if original.casefold() in folded_map:
        t = folded_map[original.casefold()]
        return t["name"], t

    # 4) Case-insensitive alias key
    aliases_folded = {k.casefold(): v for k, v in TEMPLATE_ALIASES.items()}
    alias = aliases_folded.get(original.casefold())
    if alias and alias.casefold() in folded_map:
        t = folded_map[alias.casefold()]
        return t["name"], t

    return None, None


# ============================================================
# ArchiMate XML parser
# ============================================================

def parse_archimate_for_gns3(xml_content: str, target_view_name: str):
    """
    Parse ArchiMate XML and extract:
      - GNS3 nodes based on ArchiMate properties
      - Association links only between GNS3 nodes
      - positions from the selected ArchiMate view
    """
    namespaces = {"ar": "http://www.opengroup.org/xsd/archimate/3.0/"}
    xsi_type = "{http://www.w3.org/2001/XMLSchema-instance}type"

    try:
        root = ET.fromstring(xml_content.strip())
    except ET.ParseError as e:
        print(f"CRITICAL: XML parsing failed. Error: {e}")
        return None

    # 1) Property definition map: property id -> property name
    prop_defs = {}
    prop_defs_element = root.find("ar:propertyDefinitions", namespaces)

    if prop_defs_element is not None:
        for prop_def in prop_defs_element.findall("ar:propertyDefinition", namespaces):
            prop_id = prop_def.get("identifier")
            prop_name = safe_text(
                prop_def.find("ar:name", namespaces),
                default=prop_id
            )
            prop_defs[prop_id] = prop_name

    # 2) Read ArchiMate elements and properties
    elements = {}
    elements_section = root.find("ar:elements", namespaces)

    if elements_section is not None:
        for element in elements_section.findall("ar:element", namespaces):
            elem_id = element.get("identifier")
            elem_name = safe_text(
                element.find("ar:name", namespaces),
                default="Unnamed"
            )
            elem_type = element.get(xsi_type)

            elem_data = {
                "id": elem_id,
                "name": elem_name,
                "type": elem_type,
                "properties": {},
                "x": 0,
                "y": 0,
            }

            properties_element = element.find("ar:properties", namespaces)
            if properties_element is not None:
                for prop in properties_element.findall("ar:property", namespaces):
                    prop_ref = prop.get("propertyDefinitionRef")
                    prop_name = prop_defs.get(prop_ref, prop_ref)
                    prop_value = safe_text(
                        prop.find("ar:value", namespaces),
                        default=""
                    )
                    if prop_name:
                        elem_data["properties"][prop_name] = prop_value

            elements[elem_id] = elem_data

    # 3) Read positions only from requested view
    target_view = None

    for view in root.findall(".//ar:views/ar:diagrams/ar:view", namespaces):
        view_name = safe_text(view.find("ar:name", namespaces), default="")
        if view_name == target_view_name:
            target_view = view
            break

    if target_view is None:
        print(
            f"WARNING: View '{target_view_name}' not found. "
            "Positions will default to (0,0)."
        )
    else:
        # .// catches nodes nested inside ArchiMate containers
        for node in target_view.findall(".//ar:node", namespaces):
            if node.get(xsi_type) != "Element":
                continue

            element_ref = node.get("elementRef")
            if element_ref not in elements:
                continue

            try:
                elements[element_ref]["x"] = int(node.get("x", 0))
                elements[element_ref]["y"] = int(node.get("y", 0))
            except (TypeError, ValueError):
                pass

    # 4) Collect Association relationships
    association_links = []
    relationships_section = root.find("ar:relationships", namespaces)

    if relationships_section is not None:
        for rel in relationships_section.findall("ar:relationship", namespaces):
            if rel.get(xsi_type) != "Association":
                continue

            source = rel.get("source")
            target = rel.get("target")

            if source and target:
                association_links.append({
                    "source": source,
                    "target": target,
                })

    # 5) Identify only elements that should become GNS3 nodes
    gns3_nodes = []
    element_id_to_name = {}

    allowed_node_types = {
        "qemu",
        "dynamips",
        "docker",
        "virtualbox",
        "vmware",
        "cloud",
        "ethernet_switch",
        "nat",
    }

    for elem_id, data in elements.items():
        element_id_to_name[elem_id] = data["name"]

        # Copy properties so parser normalization does not modify source data
        props = dict(data.get("properties", {}))
        node_type_raw = props.get("gns3_node_type", "")
        template_name = props.get("gns3_template", "")
        node_type = normalize_node_type(node_type_raw)

        # NAT heuristic for older ArchiMate models
        if node_type and node_type not in allowed_node_types:
            if (
                template_name.strip().lower() == "nat1"
                or "nat" in data["name"].lower()
            ):
                node_type = "nat"

        # Built-in Ethernet switch heuristic
        is_switch = (
            data["type"] == "CommunicationNetwork"
            and "switch" in data["name"].lower()
        )

        if is_switch and not node_type:
            node_type = "ethernet_switch"
            template_name = "Ethernet switch"

        if not node_type:
            continue

        props["gns3_node_type"] = node_type

        if node_type == "ethernet_switch":
            props["gns3_template"] = template_name or "Ethernet switch"

        node_info = {
            "id": elem_id,
            "name": data["name"],
            "x": data.get("x", 0),
            "y": data.get("y", 0),
            "properties": props,
        }

        gns3_nodes.append(node_info)

    normalize_positions(gns3_nodes)

    # 6) Keep links only when both ends are actual GNS3 nodes
    gns3_ids = {n["id"] for n in gns3_nodes}
    gns3_links = []

    for link in association_links:
        if link["source"] not in gns3_ids or link["target"] not in gns3_ids:
            continue

        source_name = element_id_to_name.get(link["source"])
        target_name = element_id_to_name.get(link["target"])

        if source_name and target_name:
            gns3_links.append({
                "source_node": source_name,
                "target_node": target_name,
            })

    # Remove duplicate physical links regardless of direction
    unique_links = []
    seen = set()

    for link in gns3_links:
        key = tuple(sorted((link["source_node"], link["target_node"])))
        if key not in seen:
            seen.add(key)
            unique_links.append(link)

    print(
        f"INFO: Parsed {len(gns3_nodes)} GNS3 nodes and "
        f"{len(unique_links)} links from view '{target_view_name}'."
    )

    return {
        "nodes": gns3_nodes,
        "links": unique_links,
    }



# ============================================================
# Source-model validation (before GNS3 template checks/project creation)
# ============================================================

def validate_source_topology(xml_content: str, topology: dict):
    """Check physical connection endpoints and configured switch capacities.

    This deliberately runs on the original XML, independently of the parser's
    filtered link list, so an incorrectly discarded connection is detectable.
    """
    root = ET.fromstring(xml_content.strip())
    ns = {"ar": "http://www.opengroup.org/xsd/archimate/3.0/"}
    xsi = "{http://www.w3.org/2001/XMLSchema-instance}type"
    elements = {
        item.get("identifier"): item
        for item in root.findall("ar:elements/ar:element", ns)
    }
    eligible = {node["id"]: node for node in topology["nodes"]}
    physical_relationships = []
    errors = []

    for rel in root.findall("ar:relationships/ar:relationship", ns):
        if rel.get(xsi) != "Association":
            continue
        sid, tid = rel.get("source"), rel.get("target")
        # Ignore business/semantic Associations entirely unrelated to GNS3.
        if sid not in eligible and tid not in eligible:
            continue
        if sid not in eligible or tid not in eligible:
            missing = [
                val for val in (sid, tid) if val not in eligible
            ]
            errors.append(
                f"INVALID_ENDPOINT: relationship {rel.get('identifier')} "
                f"references nondeployable/missing endpoint(s): {missing}"
            )
            continue
        physical_relationships.append((sid, tid))

    degrees = {}
    for sid, tid in physical_relationships:
        degrees[sid] = degrees.get(sid, 0) + 1
        degrees[tid] = degrees.get(tid, 0) + 1

    for node in topology["nodes"]:
        props = node.get("properties", {})
        if props.get("gns3_node_type") != "ethernet_switch":
            continue
        raw = props.get("gns3_ports", "8")
        try:
            capacity = int(raw)
        except (TypeError, ValueError):
            errors.append(f"INVALID_PORT_COUNT: {node['name']} has '{raw}'")
            continue
        if capacity < 1:
            errors.append(f"INVALID_PORT_COUNT: {node['name']} has {capacity}")
        elif degrees.get(node["id"], 0) > capacity:
            errors.append(
                f"INSUFFICIENT_PORTS: {node['name']} requires "
                f"{degrees[node['id']]} physical connections but "
                f"gns3_ports={capacity}"
            )

    return errors


# ============================================================
# GNS3 template pre-flight
# ============================================================

def preflight_templates(topology, gns3_url: str):
    """
    Validate every template-based ArchiMate node BEFORE a project is created.
    Built-in NAT, cloud, and Ethernet switch nodes do not require templates.

    Returns:
      resolved_templates: node name -> installed template record
      True/False success
    """
    print(f"\n--- Checking GNS3 templates at {gns3_url} ---")

    try:
        _, exact_map, folded_map = fetch_gns3_templates(gns3_url)
    except Exception as e:
        print(f"ERROR: Could not fetch GNS3 templates. Details: {e}")
        return {}, False

    resolved_templates = {}
    missing = []

    print("\nTEMPLATE PRE-FLIGHT:")

    for node in topology["nodes"]:
        name = node["name"]
        props = node.get("properties", {})
        node_type = props.get("gns3_node_type", "").strip().lower()
        archi_template = props.get("gns3_template", "").strip()

        if node_type in {"nat", "cloud", "ethernet_switch"}:
            print(f"  [OK] {name}: built-in GNS3 node ({node_type})")
            continue

        if node_type not in {"qemu", "dynamips", "docker", "virtualbox", "vmware"}:
            print(f"  [SKIP] {name}: unsupported node type '{node_type}'")
            continue

        resolved_name, template = resolve_template_name(
            archi_template,
            exact_map,
            folded_map,
        )

        if template is None:
            print(
                f"  [MISSING] {name}: ArchiMate template "
                f"'{archi_template}' was not found in GNS3"
            )
            missing.append((name, archi_template))
            continue

        resolved_templates[name] = template

        if resolved_name == archi_template:
            print(f"  [OK] {name}: {archi_template}")
        else:
            print(f"  [OK] {name}: {archi_template} -> {resolved_name}")

    if missing:
        print("\nPRE-FLIGHT FAILED.")
        print("No GNS3 project was created.")
        print("Missing template mappings:")
        for name, template_name in missing:
            print(f"  - {name}: '{template_name}'")
        print(
            "\nAdd/update TEMPLATE_ALIASES in this Python file "
            "or install the required template in GNS3."
        )
        return resolved_templates, False

    print(
        f"\nPRE-FLIGHT PASSED: {len(topology['nodes'])} nodes and "
        f"{len(topology['links'])} links are ready."
    )
    return resolved_templates, True


# ============================================================
# Build GNS3 project
# ============================================================

def build_gns3_project(
    topology,
    gns3_url: str,
    project_base_name: str,
    resolved_templates,
):
    print(f"\n--- Connecting to GNS3 server at {gns3_url} ---")

    try:
        server = Gns3Connector(url=gns3_url)
        # Force an actual server call
        server.get_projects()
    except Exception as e:
        print(
            "ERROR: Could not connect to GNS3 server. "
            f"Ensure GNS3 is running. Details: {e}"
        )
        return None

    new_project_name = unique_project_name(project_base_name, server)
    print(
        "Creating a NEW project (existing projects are kept). "
        f"New name: '{new_project_name}'"
    )

    # Save the generated GNS3 project beside this parser
    project_path = os.path.join(SCRIPT_DIR, new_project_name)

    try:
        project_url = f"{gns3_url.rstrip('/')}/v2/projects"
        response = requests.post(
            project_url,
            json={
                "name": new_project_name,
                "path": project_path,
            },
            timeout=CREATE_TIMEOUT,
        )
        response.raise_for_status()
        response = response.json()

        project_id = response["project_id"]
        saved_path = response.get("path") or project_path

        print(
            f"Project '{response['name']}' created successfully "
            f"with ID: {project_id}"
        )
        print(f"Project saved in: {saved_path}")
    except Exception as e:
        print(f"ERROR: Could not create project. Details: {e}")
        return None

    created_nodes_data = {}

    print("\nCREATING NODES:")

    for node_data in topology["nodes"]:
        name = node_data["name"]
        props = node_data.get("properties", {})
        node_type = props.get("gns3_node_type", "").strip().lower()
        archi_template_name = props.get("gns3_template", "").strip()

        payload = {
            "name": name,
            "x": node_data.get("x", 0),
            "y": node_data.get("y", 0),
        }

        try:
            # Built-in NAT
            if node_type == "nat":
                print(f"  - Creating '{name}' as built-in NAT...")
                payload["symbol"] = ":/symbols/cloud.svg"
                payload["node_type"] = "nat"
                payload["compute_id"] = "local"
                url = f"{gns3_url.rstrip('/')}/v2/projects/{project_id}/nodes"

            # Built-in cloud
            elif node_type == "cloud":
                print(f"  - Creating '{name}' as built-in Cloud...")
                payload["symbol"] = ":/symbols/cloud.svg"
                payload["node_type"] = "cloud"
                payload["compute_id"] = "local"
                url = f"{gns3_url.rstrip('/')}/v2/projects/{project_id}/nodes"

            # Built-in Ethernet switch
            elif node_type == "ethernet_switch":
                print(f"  - Creating '{name}' as built-in Ethernet switch...")

                try:
                    switch_port_count = int(props.get("gns3_ports", 8))
                except (TypeError, ValueError):
                    switch_port_count = 8

                if switch_port_count < 1:
                    switch_port_count = 8

                ports_mapping = [
                    {
                        "name": f"Ethernet{i}",
                        "port_number": i,
                        "type": "access",
                        "vlan": 1,
                    }
                    for i in range(switch_port_count)
                ]

                payload["symbol"] = ":/symbols/ethernet_switch.svg"
                payload["node_type"] = "ethernet_switch"
                payload["compute_id"] = "local"
                payload["properties"] = {
                    "ports_mapping": ports_mapping
                }

                print(
                    f"    - ArchiMate requested "
                    f"{switch_port_count} Ethernet ports."
                )

                url = (
                    f"{gns3_url.rstrip('/')}/v2/projects/"
                    f"{project_id}/nodes"
                )
            elif node_type in {"qemu", "dynamips", "docker", "virtualbox", "vmware"}:
                template = resolved_templates.get(name)
                if not template:
                    print(f"    - ERROR: No resolved template for '{name}'. Skipping.")
                    continue

                resolved_name = template["name"]
                template_id = template["template_id"]

                if resolved_name == archi_template_name:
                    print(f"  - Creating '{name}' from template '{resolved_name}'...")
                else:
                    print(
                        f"  - Creating '{name}': ArchiMate "
                        f"'{archi_template_name}' -> GNS3 '{resolved_name}'..."
                    )

                url = (
                    f"{gns3_url.rstrip('/')}/v2/projects/{project_id}/"
                    f"templates/{template_id}"
                )

            else:
                print(
                    f"  - WARNING: Unknown node type '{node_type}'. "
                    f"Skipping '{name}'."
                )
                continue

            response = requests.post(url, json=payload, timeout=CREATE_TIMEOUT)
            response.raise_for_status()

            node_info = response.json()
            created_nodes_data[name] = node_info

            print(
                f"    - SUCCESS: '{name}' node_id={node_info['node_id']} "
                f"at ({payload['x']},{payload['y']})"
            )

        except Exception as e:
            print(f"    - ERROR: Failed to create '{name}'. Details: {e}")

    # --------------------------------------------------------
    # Create physical links
    # --------------------------------------------------------

    print("\nCREATING LINKS:")
    port_tracker = {}

    def get_free_ports(node_id):
        url = (
            f"{gns3_url.rstrip('/')}/v2/projects/{project_id}/"
            f"nodes/{node_id}"
        )
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        node_details = response.json()

        return [
            port
            for port in node_details.get("ports", [])
            if "ethernet" in port.get("link_type", "").lower()
            and port.get("link_id") is None
        ]

    links_created = 0

    for link_data in topology["links"]:
        source_name = link_data["source_node"]
        target_name = link_data["target_node"]

        if source_name not in created_nodes_data or target_name not in created_nodes_data:
            print(
                f"  - WARNING: Skipping {source_name}<->{target_name}; "
                "one or both nodes were not created."
            )
            continue

        print(f"  - Linking '{source_name}' <--> '{target_name}'")

        try:
            source_id = created_nodes_data[source_name]["node_id"]
            target_id = created_nodes_data[target_name]["node_id"]

            if source_id not in port_tracker:
                port_tracker[source_id] = get_free_ports(source_id)

            if target_id not in port_tracker:
                port_tracker[target_id] = get_free_ports(target_id)

            if not port_tracker[source_id]:
                print(f"    - ERROR: No free Ethernet ports on '{source_name}'.")
                continue

            if not port_tracker[target_id]:
                print(f"    - ERROR: No free Ethernet ports on '{target_name}'.")
                continue

            source_port = port_tracker[source_id].pop(0)
            target_port = port_tracker[target_id].pop(0)

            payload = {
                "nodes": [
                    {
                        "adapter_number": source_port["adapter_number"],
                        "port_number": source_port["port_number"],
                        "node_id": source_id,
                    },
                    {
                        "adapter_number": target_port["adapter_number"],
                        "port_number": target_port["port_number"],
                        "node_id": target_id,
                    },
                ]
            }

            url = f"{gns3_url.rstrip('/')}/v2/projects/{project_id}/links"

            response = requests.post(url, json=payload, timeout=CREATE_TIMEOUT)
            response.raise_for_status()

            links_created += 1
            print("    - SUCCESS: Link created.")

        except Exception as e:
            print(
                f"    - ERROR: Failed to link '{source_name}' and "
                f"'{target_name}'. Details: {e}"
            )

    print("\n--- GNS3 Project Build Complete ---")
    print(f"Project: '{new_project_name}'")
    print(
        f"Created {len(created_nodes_data)}/{len(topology['nodes'])} nodes "
        f"and {links_created}/{len(topology['links'])} links."
    )

    if len(created_nodes_data) != len(topology["nodes"]):
        print("WARNING: The project was created but one or more nodes failed.")

    if links_created != len(topology["links"]):
        print("WARNING: The project was created but one or more links failed.")

    print(f"Open project in GNS3: '{new_project_name}'")
    return new_project_name


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "A2G Parser 12: Parse ArchiMate XML and generate a NEW "
            "GNS3 project without modifying the XML or deleting "
            "existing projects."
        )
    )

    parser.add_argument(
        "--xml",
        default=DEFAULT_XML_FILENAME,
        help=f"ArchiMate XML export (default: {DEFAULT_XML_FILENAME})",
    )

    parser.add_argument(
        "--gns3-url",
        default=DEFAULT_GNS3_URL,
        help=f"GNS3 server URL (default: {DEFAULT_GNS3_URL})",
    )

    parser.add_argument(
        "--project-base",
        default=DEFAULT_GNS3_PROJECT_BASE_NAME,
        help=(
            "Base name for generated projects. "
            "A timestamp is appended automatically."
        ),
    )

    parser.add_argument(
        "--view",
        default=DEFAULT_TARGET_VIEW_NAME,
        help="ArchiMate view used to obtain node positions.",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Parse XML and validate installed GNS3 templates, "
            "but do not create a GNS3 project."
        ),
    )

    args = parser.parse_args()

    print("============================================================")
    print("A2G Parser 12 - ArchiMate -> GNS3")
    print("============================================================")
    print(f"Pydantic version: {pydantic.__version__}")
    print(f"XML: {args.xml}")
    print(f"GNS3: {args.gns3_url}")
    print(f"View: {args.view}")

    # Safety lock
    protected_folded = {name.casefold() for name in PROTECTED_PROJECT_NAMES}
    if args.project_base.casefold() in protected_folded:
        print("\nFATAL: The requested project base name is protected.")
        print(f"Protected names: {sorted(PROTECTED_PROJECT_NAMES)}")
        print("Use a safe base name such as A2G_AutoGen.")
        raise SystemExit(3)

    # Read XML
    if not os.path.exists(args.xml):
        print(f"\nFATAL: XML file '{args.xml}' was not found.")
        print("Put the XML beside this script or pass its path with --xml.")
        raise SystemExit(1)

    with open(args.xml, "r", encoding="utf-8-sig") as file:
        xml_data = file.read().strip()

    topology = parse_archimate_for_gns3(
        xml_data,
        target_view_name=args.view,
    )

    if not topology:
        raise SystemExit(2)

    validation_errors = validate_source_topology(xml_data, topology)
    if validation_errors:
        print("\nSOURCE-MODEL VALIDATION FAILED. No GNS3 project was created.")
        for err in validation_errors:
            print(f"  - {err}")
        raise SystemExit(6)

    print("\n--- Parsed Topology ---")
    print(json.dumps(topology, indent=2))

    # Validate all installed GNS3 templates before creating anything
    resolved_templates, preflight_ok = preflight_templates(
        topology,
        gns3_url=args.gns3_url,
    )

    if not preflight_ok:
        raise SystemExit(4)

    if args.dry_run:
        print("\nDRY RUN COMPLETE.")
        print("XML was not modified.")
        print("No GNS3 project was created.")
        return

    result = build_gns3_project(
        topology,
        gns3_url=args.gns3_url,
        project_base_name=args.project_base,
        resolved_templates=resolved_templates,
    )

    if result is None:
        raise SystemExit(5)


if __name__ == "__main__":
    main()
