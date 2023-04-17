rm -r build dist

python setup.py bdist_wheel --universal

python3 -m twine upload dist/* --verbose
