import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
     name='reacher',  
     version='0.1',
     # scripts=['reacher.py'] ,
     author="johannes skog",
     author_email="johannes.skog.unsec@gmail.com",
     description="A Docker and AWS utility package",
     long_description=long_description,
   long_description_content_type="text/markdown",
     url="https://github.com/javatechy/dokr",
     packages=["reacher"],
     install_requires=[
        'scp', "paramiko",
     ],
     classifiers=[
         "Programming Language :: Python :: 3",
         "License :: OSI Approved :: MIT License",
         "Operating System :: OS Independent",
     ],
 )