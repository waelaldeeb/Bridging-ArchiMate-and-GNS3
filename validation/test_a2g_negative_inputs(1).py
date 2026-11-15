#!/usr/bin/env python3
"""Offline validation regression tests. GNS3 API/template inventory is mocked.
No real GNS3 projects are created. Run: python test_a2g_negative_inputs.py
"""
from pathlib import Path
import importlib.util
import json
import sys
import types
import xml.etree.ElementTree as ET

sys.modules.setdefault('gns3fy', types.SimpleNamespace(Gns3Connector=object))
module_path = Path(__file__).with_name('A2G_52_validated.py')
spec = importlib.util.spec_from_file_location('a2g_validated', module_path)
a2g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a2g)
xml_path = Path(__file__).with_name('A2G-52 nodes(8).xml')
original = xml_path.read_text(encoding='utf-8-sig')
NS = {'ar': 'http://www.opengroup.org/xsd/archimate/3.0/'}
XSI = '{http://www.w3.org/2001/XMLSchema-instance}type'


def parse(s):
    return a2g.parse_archimate_for_gns3(s, a2g.DEFAULT_TARGET_VIEW_NAME)


def serialized(root):
    return ET.tostring(root, encoding='unicode')


results = []
base_topology = parse(original)
base_errors = a2g.validate_source_topology(original, base_topology)
assert not base_errors, base_errors
results.append({'test': 'Baseline', 'expected': 'valid topology', 'observed': 'accepted',
                'nodes': len(base_topology['nodes']), 'links': len(base_topology['links']), 'pass': True})

# N1: physical connection references a nonexistent ArchiMate element.
r = ET.fromstring(original)
association = next(rel for rel in r.findall('ar:relationships/ar:relationship', NS)
                   if rel.get(XSI) == 'Association')
association.set('target', 'id-NONEXISTENT-TEST-ENDPOINT')
modified = serialized(r)
errors = a2g.validate_source_topology(modified, parse(modified))
assert any('INVALID_ENDPOINT' in err for err in errors), errors
results.append({'test': 'N1 missing endpoint', 'expected': 'INVALID_ENDPOINT',
                'observed': errors, 'pass': True})

# N2: Switch 1 needs 17 links but is assigned only 16 ports.
r = ET.fromstring(original)
propmap = {p.get('identifier'): p.find('ar:name', NS).text
           for p in r.findall('ar:propertyDefinitions/ar:propertyDefinition', NS)}
for el in r.findall('ar:elements/ar:element', NS):
    if el.find('ar:name', NS).text == 'Switch 1':
        for p in el.findall('ar:properties/ar:property', NS):
            if propmap.get(p.get('propertyDefinitionRef')) == 'gns3_ports':
                p.find('ar:value', NS).text = '16'
                break
        else:
            raise AssertionError('Switch 1 gns3_ports not found')
        break
modified = serialized(r)
errors = a2g.validate_source_topology(modified, parse(modified))
assert any('INSUFFICIENT_PORTS' in err and '17' in err for err in errors), errors
results.append({'test': 'N2 insufficient ports', 'expected': 'INSUFFICIENT_PORTS',
                'observed': errors, 'pass': True})

# N3: unknown template; installed inventory simulated locally for offline test.
r = ET.fromstring(original)
for el in r.findall('ar:elements/ar:element', NS):
    if el.find('ar:name', NS).text == 'PC 01':
        for p in el.findall('ar:properties/ar:property', NS):
            if propmap.get(p.get('propertyDefinitionRef')) == 'gns3_template':
                p.find('ar:value', NS).text = 'Nonexistent-Template-N3'
                break
        break
modified = serialized(r)
changed = parse(modified)
assert not a2g.validate_source_topology(modified, changed)
# Simulate the known expected template names and avoid network access.
base_template_names = {
    a2g.TEMPLATE_ALIASES.get(n['properties']['gns3_template'], n['properties']['gns3_template'])
    for n in base_topology['nodes']
    if n['properties'].get('gns3_node_type') not in {'nat', 'cloud', 'ethernet_switch'}
}
inventory = [{'name': name, 'template_id': f'test-{i}'}
             for i, name in enumerate(sorted(base_template_names))]
a2g.fetch_gns3_templates = lambda _url: (
    inventory,
    {t['name']: t for t in inventory},
    {t['name'].casefold(): t for t in inventory}
)
_, ok = a2g.preflight_templates(changed, 'http://mocked-no-server')
assert not ok
results.append({'test': 'N3 unavailable template', 'expected': 'preflight failure',
                'observed': 'PRE-FLIGHT FAILED (mocked template inventory)', 'pass': True})

report = {
    'scope': 'Offline regression checks against actual submitted ArchiMate XML and revised parser',
    'caveat': 'N3 mocks installed GNS3 templates; no live GNS3 server or device deployment tested',
    'tests': results
}
Path(__file__).with_name('a2g_negative_test_results.json').write_text(json.dumps(report, indent=2))
print('\n' + json.dumps(report, indent=2))
