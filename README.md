**Usage:**

	zero2pypi feed-name.xml
	./setup.py update

*Note:* This will blanketly overwrite any existing `setup.py`. Make sure
that's okay.

If it guesses incorrect dependency names, you can tell it the exact mapping
by placing a line of the form

	<url> <pypi-name>

in either `./.zero2pypi` or `~/.zero2pypi`.

E.g.:

	http://gfxmonk.net/dist/0install/python-snakefood.xml snakefood

You can have as many mapping as you like, one per line.
