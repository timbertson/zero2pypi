#!/usr/bin/env python3
import os
import re
import optparse
from xml.dom.minidom import parse, Element


ns = "http://zero-install.sourceforge.net/2004/injector/interface"
gfxmonk_ns = "http://gfxmonk.net/dist/0install"
zero2pypi_feed = "http://gfxmonk.net/dist/0install/zero2pypi.xml"

attrs = {}
name_extractor = re.compile('(?P<name>[^/.]+)(\.xml)?$')

def get_mapping():
	mapping = {}
	def read_mapping(filename):
		try:
			with open(filename) as f:
				lines = filter(None, map(lambda s: s.strip(), f.readlines()))
				for line in lines:
					k, v = line.split()
					mapping[k] = v
		except (IOError, OSError):
			pass
	read_mapping(os.path.expanduser('~/.zero2pypi'))
	read_mapping('.zero2pypi')
	return mapping

zero_to_pypi_package_mapping = get_mapping()

def extract_name_for_url(url):
	def get_translated(name):
		try:
			return zero_to_pypi_package_mapping[name]
		except KeyError: pass
	name = name_extractor.search(url).groupdict()['name']
	return get_translated(url) or get_translated(name) or name

def get_dependency_names(requirements):
	names = ['setuptools']
	for requirement in requirements:
		url = requirement.getAttribute('interface')
		name = extract_name_for_url(url)
		print("assuming http://pypi.python.org/pypi/%s for (%s)\n" % (name, url))
		if name == 'python':
			print("Skipping dependency on \"python\"...")
			continue
		version_specs = requirement.getElementsByTagNameNS(ns, "version") or []
		conditions = []
		for version_spec in version_specs:
			not_before = version_spec.getAttribute("not-before")
			before = version_spec.getAttribute("before")
			if not_before:
				conditions.append(">=%s" % (not_before,))
			if before:
				conditions.append("<%s" % (before,))
		if conditions:
			print(repr(conditions))
			name += " " + ", ".join(conditions)
		names.append(name)
	return names

def get_text(dom, nodename, ns=ns):
	elem = dom.getElementsByTagNameNS(ns, nodename)
	if elem:
		return str(elem[0].childNodes[0].data).strip()
	else:
		return None

def get_main_command(group):
	main_attr = group.getAttribute("main")
	if main_attr: return main_attr
	command_elements = group.getElementsByTagNameNS(ns, "command")
	main_commands = list(filter(lambda cmd: cmd.getAttribute("name") == 'run', command_elements))
	if main_commands:
		return main_commands[0].getAttribute('path')
	return None

def load_attrs(feed):
	attrs = {}
	with open(feed) as f:
		dom = parse(f)
	latest_group = dom.getElementsByTagNameNS(ns, "group")[-1]
	latest_implementation = latest_group.getElementsByTagNameNS(ns, "implementation")[-1]
	group_requires = [tag for tag in latest_group.childNodes if tag.nodeType == Element.ELEMENT_NODE and tag.tagName == "requires"]
	implementation_requires = latest_implementation.getElementsByTagNameNS(ns, "requires") or []
	attrs['version'] = latest_implementation.getAttribute('version')

	uri = attrs['url'] = dom.documentElement.getAttribute("uri") or dom.getElementsByTagNameNS(ns, 'feed-for')[0].getAttribute('interface')
	name = attrs['name'] = os.path.splitext(os.path.basename(feed))[0]

	dependency_names = get_dependency_names(group_requires + implementation_requires)
	if dependency_names:
		attrs['install_requires'] = dependency_names
	
	populate_entry_points(name, latest_group, attrs)
	populate_pypi_extras(dom, attrs)
	populate_download_url(latest_implementation, attrs) # setuptools is too stupid for this to work.
	populate_py_modules(attrs)

	summary = get_text(dom, "summary")
	if summary:
		attrs['description'] = summary

	description = get_text(dom, "description") or ""
	description = """
**Note**: This package has been built automatically by
`zero2pypi <{tool_uri}>`_.
If possible, you should use the zero-install feed instead:
{uri}

----------------

{description}
""".format(description=description, tool_uri=zero2pypi_feed, uri=uri)
	attrs['long_description'] = description
	make_string_values(attrs)
	return attrs

def populate_download_url(latest_implementation, attrs):
	download_urls = latest_implementation.getElementsByTagNameNS(ns, 'archive') or []
	download_urls = list(filter(None, [impl.getAttribute('href') for impl in download_urls]))
	if download_urls:
		url = download_urls[0]
		if '://' in url:
			attrs['download_url'] = url

def populate_py_modules(attrs):
	ext = '.py'
	is_py = lambda filename: filename.endswith(ext)
	just_module = lambda filename: filename[:-len(ext)]
	not_test_file = lambda module: not (module.startswith('test') or module.endswith('test'))
	py_modules = set(filter(not_test_file, map(just_module, filter(is_py, os.listdir('.')))))
	py_modules.difference_update(set(['setup', 'test', 'conf']))
	if py_modules:
		attrs['py_modules'] = list(sorted(py_modules))

def populate_pypi_extras(dom, attrs):
	extras = get_text(dom, 'pypi-extra', ns=gfxmonk_ns)
	if extras:
		attrs['extras'] = extras

def populate_entry_points(program_name, latest_group, attrs):
	group_envs = latest_group.getElementsByTagNameNS(ns, "environment") or []
	main = get_main_command(latest_group)
	def add_entry_point(name, value):
		if 'entry_points' not in attrs:
			attrs['entry_points'] = {}
		attrs['entry_points'][name] = value

	if main:
		if main.endswith(".py"):
			entry_point = ".".join((main[:-3].split(os.path.sep))) + ":main"
			print("assuming %s entry point for executable python script %s" % (entry_point, main))
			add_entry_point('console_scripts', ["%s=%s" % (program_name, entry_point)])
		else:
			attrs['scripts'] = [main]
	for env in group_envs:
		entry_point = env_to_entry_point(env)
		if entry_point:
			add_entry_point(*entry_point)

def env_to_entry_point(env):
	name = env.getAttribute('name')
	if name == 'NOSETESTS_PLUGINS':
		value = env.getAttribute('insert') or env.getAttribute('value')
		return ( 'nose.plugins.0.10', ['%s = %s' % (name, value.replace('/', ':'))] )
	return None

def make_string_values(d):
	for k,v in d.items():
		if isinstance(v, bytes):
			d[k] = v.decode('UTF-8')

def write_setup_py(attrs, filename):
	extras = attrs.pop('extras', None)
	lines = ["\t%s=%s," % (k,repr(v)) for k,v in sorted(attrs.items())]
	if extras:
		lines.append(extras)
	result = """#!/usr/bin/env python

## NOTE: ##
## this setup.py was generated by zero2pypi:
## %s

from setuptools import *
setup(
	packages = find_packages(exclude=['test', 'test.*']),
%s
)
""" % (zero2pypi_feed, "\n".join(lines),)
	with open(filename, 'w') as setup:
		setup.write(result)

import stat
def chmod_x(filename):
	"""
	ensure file has all execute permissions
	(like chmod a+x <filename>)
	"""
	mode = os.stat(filename).st_mode
	os.chmod(filename, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

def main():
	p = optparse.OptionParser()
	opts, args = p.parse_args()
	feed_name, = args
	attrs = load_attrs(feed_name)
	dest = 'setup.py'
	write_setup_py(attrs, dest)
	chmod_x(dest)
	print("# Now run:\n./%s register" % (dest,))

if __name__ == '__main__':
	main()
