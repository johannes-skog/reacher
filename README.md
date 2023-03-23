# Reacher

From your local machine, Reacher will,

+ build a docker image on the remote (docker must already be installed and ssh enabled) according to specifications
+ set up container on the remote with port port-forwarding and enviroment variables 
+ execute your local code on the remote, in the container, with printouts shown as your were running it locally
+ upload/download files from the container to your local machine


# Getting started...

To get started,

```bash
pip install reacher
pip install python-dotenv
```

First we must setup a connection to the remote, RemoteClient will create a ssh connection between the local and remote machine.

```python
from reacher.reacher import Reacher, RemoteClient
from dotenv import dotenv_values
config = dotenv_values()  # take environment variables from .env.
client = RemoteClient(
    host=config["HOST"],
    user=config["USER"],
    password=config["PASSWORD"],
    ssh_key_filepath=config["SSH_KEY_PATH"]
)
```

the connection is sent to Reacher together with the name of the image that we want to build and the name of the container.

```python
reacher = Reacher(
    client=client,
    build_name="base",
    image_name="base",
    build_context="dockercontext"
)
```
build_context should contain everything for building the docker image on the remote. It might look like,

```bash
$ ls dockercontext/
Dockerfile  requirements.txt
```

Once Reacher has been setup we can build the image on the remote. Reacher will send the build_context to the remote and
trigger docker to build an image according to the specifications in the Dockerfile

```python
reacher.build()

[+] Building 0.0s (0/1)                                                         
[+] Building 0.2s (2/3)                                                         
 => [internal] load .dockerignore                                          0.0s
 => => transferring context: 2B                                            0.0s
 => [internal] load build definition from Dockerfile                       0.0s
 => => transferring dockerfile: 528B                                       0.0
 ...
 ...
```

and thereafter we can setup the docker container. Reacher will make sure this container is running until we have explicitly deleted it.

```python
reacher.setup(ports=[8888, 6666], envs=dotenv_values(".env"))
```

# Running code on the remote 

## Running a code-snippet 

Now we have built the docker image on the remote and have a container ready to execute whatever code that we want to run.

A "Hello World" test can be triggered from a notebook.

First we create the python module that we want to execute,


```python
%%writefile simple_test.py
import time
while 1:
    print("Hello from remote")
    time.sleep(1)
```

and then we execute it on the remote inside our controlled docker enviroment.

```python
reacher.execute(
    file="simple_test.py",
    command="python simple_test.py",
    named_session="simple_test",
    # Before sending the code to the remote, clean the container from previous runs.
    clear_container=True, 
)

Preparing to copy...

Copying to container - 2.56kB

Successfully copied 2.56kB to base://workspace

Hello from remote
Hello from remote
...
```

simple_test will continue to run in the background (even if you kill the cell/script that you instantiated the reacher.execute from) until we explicitly have killed it.

With list_named_sessions you can get all currently running sessions.

```python
reacher.list_named_sessions()
There is a screen on:
	22.simple_test	(03/19/23 18:20:07)	(Attached)
1 Socket in /run/screen/S-root.
```

we can always attach to a named session to continue to get printouts.


```python
reacher.attach_named_session("simple_test")
```

or kill it

```python
reacher.kill_named_session("simple_test")
```

## Running with dependencies 

To execute some code that depends on other modules inside a src directory, simply add src as a context_folder when calling 
reacher.execute.

```python
%%writefile dependency_test.py
from dependency import Dependency
d = Dependency()
```

```python
reacher.execute(
    context_folder="src",
    file="dependency_test.py",
    command="python dependency_test.py",
    named_session="dependency_test",
)

Preparing to copy...

Copying to container - 3.584kB

Successfully copied 3.584kB to base://workspace

Hello from class Dependency
[screen is terminating]
```

## Generate artifact 

In many cases we want to run some code on the remote and afterwards collect some artifacts.

Everything that is saved in the artifact directory will be available for us to download to the local machine. 
