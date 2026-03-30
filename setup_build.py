import os
import sys
import glob
from setuptools import setup, Extension
from Cython.Build import cythonize

# Collect all python files to compile
py_files = []
for file in glob.glob("**/*.py", recursive=True):
    if file not in ["setup_build.py", "build_plugin.py", "__init__.py"]:
        if "tests" not in file and "venv" not in file and "dist" not in file and ".git" not in file and ".agents" not in file:
            py_files.append(file)

print(f"Compiling {len(py_files)} files...")

extensions = [Extension(f.replace(os.path.sep, ".")[:-3], [f]) for f in py_files]

setup(
    ext_modules=cythonize(extensions, compiler_directives={'language_level': "3"}),
    script_args=["build_ext", "--inplace"]
)
