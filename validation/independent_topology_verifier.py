#!/usr/bin/env python3
"""Independent ArchiMate XML vs GNS3 .gns3 structural topology verifier.

Uses only Python's standard library; does NOT import the A2G transformation parser.
Usage:
    python independent_topology_verifier.py source.xml project.gns3
    python independent_topology_verifier.py source.xml project.gns3 --out report.json

Scope: selected GNS3-eligible source elements, Association links, node identities,
undirected endpoint pairs, port usage and switch capacity. It does not validate
running device configurations or source-to-target identifier JSON records.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

ARCH = '{http://www.opengroup.org/xsd/archimate/3.0/}'
XSI = '{http://www.w3.org/2001/XMLSchema-instance}'


def canon(name):
    """Normalize spacing and punctuation differences in A2G-created node labels."""
    return re.sub(r'[^a-z0-9]', '', name.casefold())


def load_source(path):
    root = ET.parse(path).getroot()
    defs = {d.attrib['identifier']: d.findtext(ARCH + 'name', default='')
            for d in root.findall(f'{ARCH}propertyDefinitions/{ARCH}propertyDefinition')}
    all_elements, eligible = {}, {}
    for element in root.findall(f'{ARCH}elements/{ARCH}element'):
        eid = element.attrib['identifier']
        name = element.findtext(ARCH + 'name', default='')
        typ = element.attrib.get(XSI + 'type', '')
        props = {}
        for prop in element.findall(f'{ARCH}properties/{ARCH}property'):
            props[defs.get(prop.attrib.get('propertyDefinitionRef'), '')] = prop.findtext(ARCH + 'value', default='')
        all_elements[eid] = {'name': name, 'type': typ, 'properties': props}
        # Explicit GNS3 annotation, or conventionally mapped Ethernet switch.
        if props.get('gns3_node_type') or (typ == 'CommunicationNetwork' and
                                          props.get('gns3_template') == 'Ethernet Switch'):
            eligible[eid] = all_elements[eid]
    relationships = []
    dangling = []
    for rel in root.findall(f'{ARCH}relationships/{ARCH}relationship'):
        if rel.attrib.get(XSI + 'type') != 'Association':
            continue
        s, t = rel.attrib.get('source'), rel.attrib.get('target')
        if s in eligible and t in eligible:
            relationships.append({'id': rel.attrib.get('identifier'), 'source': s, 'target': t})
        elif s not in all_elements or t not in all_elements:
            dangling.append(rel.attrib.get('identifier'))
    return eligible, relationships, dangling


def load_gns3(path):
    project = json.loads(Path(path).read_text(encoding='utf-8'))
    topology = project['topology']
    return topology['nodes'], topology['links'], project.get('name', '')


def report_for(source_file, project_file):
    elements, relationships, dangling = load_source(source_file)
    nodes, links, name = load_gns3(project_file)
    src_names = Counter(canon(v['name']) for v in elements.values())
    tgt_names = Counter(canon(v['name']) for v in nodes)
    id_to_name = {node['node_id']: canon(node['name']) for node in nodes}
    id_to_node = {node['node_id']: node for node in nodes}
    src_pairs = Counter(tuple(sorted((canon(elements[r['source']]['name']),
                                      canon(elements[r['target']]['name']))))
                        for r in relationships)
    target_pairs = Counter()
    invalid_link_ids = []
    endpoint_counts = Counter()
    for link in links:
        ends = link.get('nodes', [])
        if len(ends) != 2 or any(e.get('node_id') not in id_to_name for e in ends):
            invalid_link_ids.append(link.get('link_id', '(missing link ID)'))
            continue
        target_pairs[tuple(sorted(id_to_name[e['node_id']] for e in ends))] += 1
        for e in ends:
            endpoint_counts[(e['node_id'], e.get('adapter_number'), e.get('port_number'))] += 1
    source_port_capacity = {}
    for element in elements.values():
        if element['properties'].get('gns3_template') == 'Ethernet Switch':
            value = element['properties'].get('gns3_ports')
            if value and value.isdigit():
                source_port_capacity[canon(element['name'])] = int(value)
    switch_details = []
    for n in nodes:
        if n.get('node_type') != 'ethernet_switch':
            continue
        cname = canon(n['name'])
        capacity = len(n.get('properties', {}).get('ports_mapping', []))
        used = sum(1 for link in links for ep in link.get('nodes', []) if ep.get('node_id') == n['node_id'])
        switch_details.append({'name': n['name'], 'source_ports': source_port_capacity.get(cname),
                               'generated_ports': capacity, 'used_links': used,
                               'capacity_sufficient': used <= capacity and
                               (source_port_capacity.get(cname) is None or
                                source_port_capacity[cname] == capacity)})
    missing_nodes = list((src_names - tgt_names).elements())
    extra_nodes = list((tgt_names - src_names).elements())
    missing_edges = [{'endpoints': list(k), 'count': v} for k, v in (src_pairs - target_pairs).items()]
    extra_edges = [{'endpoints': list(k), 'count': v} for k, v in (target_pairs - src_pairs).items()]
    collisions = [{'node_id': nid, 'adapter': adapter, 'port': port, 'uses': count}
                  for (nid, adapter, port), count in endpoint_counts.items() if count > 1]
    duplicate_names = [n for n, c in src_names.items() if c > 1] + [n for n, c in tgt_names.items() if c > 1]
    passed = not any([missing_nodes, extra_nodes, missing_edges, extra_edges, invalid_link_ids,
                      collisions, duplicate_names, dangling,
                      any(not s['capacity_sufficient'] for s in switch_details)])
    return {'result': 'PASS' if passed else 'FAIL',
            'scope': 'Structural source-to-target comparison, not runtime configuration or traceability JSON validation',
            'source_file': str(source_file), 'gns3_file': str(project_file), 'gns3_project_name': name,
            'expected_nodes': len(elements), 'generated_nodes': len(nodes),
            'expected_physical_links': len(relationships), 'generated_physical_links': len(links),
            'matched_node_names': sum((src_names & tgt_names).values()),
            'matched_link_endpoint_pairs': sum((src_pairs & target_pairs).values()),
            'missing_nodes': missing_nodes, 'unexpected_nodes': extra_nodes,
            'missing_links': missing_edges, 'unexpected_links': extra_edges,
            'invalid_link_endpoints': invalid_link_ids, 'duplicate_interface_allocations': collisions,
            'duplicate_normalized_names': duplicate_names,
            'dangling_source_associations': dangling, 'switch_port_checks': switch_details,
            'method': 'Independent XML parsing and GNS3 JSON parsing; canonicalized device names and undirected endpoint multisets; no transformation code reused.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_xml')
    parser.add_argument('project_gns3')
    parser.add_argument('--out', help='Write detailed JSON report')
    args = parser.parse_args()
    result = report_for(args.source_xml, args.project_gns3)
    print(json.dumps(result, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    sys.exit(0 if result['result'] == 'PASS' else 1)

if __name__ == '__main__':
    main()
