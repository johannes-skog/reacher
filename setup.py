import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
     name='reacher',  
     version='0.3.6',
     author="johannes skog",
     author_email="johannes.skog.unsec@gmail.com",
     description="A tool for reaching out to remote machine - excecute code and collect artificats",
     long_description=long_description,
   long_description_content_type="text/markdown",
     url="https://github.com/johannes-skog/reacher",
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
