
import os
from typing import List, Dict, Union
import uuid
from os import system
from typing import List
import os
from paramiko import AutoAddPolicy, RSAKey, SSHClient
from paramiko.auth_handler import AuthenticationException, SSHException
from scp import SCPClient, SCPException
import logging
import socket
import select
import sys
import time

try:
    import SocketServer
except ImportError:
    import socketserver as SocketServer

# Define progress callback that prints the current percentage completed for the file
def progress4(filename, size, sent, peername):
    sys.stdout.write("(%s:%s) %s's progress: %.2f%%   \r" % (peername[0], peername[1], filename, float(sent)/float(size)*100) )

class RemoteClient:
    """Client to interact with a remote host via SSH & SCP."""

    def __init__(
        self,
        host: str,
        user: str,
        ssh_key_filepath: str,
        port: int = 22,
        password: str = None,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.ssh_key_filepath = ssh_key_filepath
        self.port = port
        self.client = None
        self._upload_ssh_key()

    @property
    def connection(self):
        try:
            client = SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(AutoAddPolicy())
            client.connect(
                self.host,
                username=self.user,
                password=self.password,
                key_filename=self.ssh_key_filepath,
                timeout=10000,
                port=self.port,
            )
            return client
        except AuthenticationException as e:
            logging.error(
                f"AuthenticationException occurred; did you remember to generate an SSH key? {e}"
            )
        except Exception as e:
            logging.error(f"Unexpected error occurred while connecting to host: {e}")

    @property
    def scp(self) -> SCPClient:
        conn = self.connection
        return SCPClient(conn.get_transport(), progress4=progress4)

    def _get_ssh_key(self):
        try:
            self.ssh_key = RSAKey.from_private_key_file(self.ssh_key_filepath)
            logging.info(f"Found SSH key at self {self.ssh_key_filepath}")
            return self.ssh_key
        except SSHException as e:
            logging.error(f"SSHException while getting SSH key: {e}")
        except Exception as e:
            logging.error(f"Unexpected error while getting SSH key: {e}")

    def _upload_ssh_key(self):
        try:
            system(
                f"ssh-copy-id -i {self.ssh_key_filepath}.pub {self.user}@{self.host}>/dev/null 2>&1"
            )
            logging.info(f"{self.ssh_key_filepath} uploaded to {self.host}")
        except FileNotFoundError as e:
            logging.error(f"FileNotFoundError while uploading SSH key: {e}")
        except Exception as e:
            logging.error(f"Unexpected error while uploading SSH key: {e}")

    def disconnect(self):
        if self.connection:
            self.client.close()
        if self.scp:
            self.scp.close()

    def upload_file(self, filepath: str, remote_path: str, excluded_exts: List[str] = [".pyc"]):

        if not any(filepath.endswith(ext) for ext in excluded_exts):
            self.scp.put(filepath, remote_path)
            logging.info(f"Finished uploading {filepath} to {remote_path} on {self.host}")
        else:
            logging.info(f"Skipping {filepath} due to excluded extension")
    
    def _upload(self, filepath: str, remote_path: str, excluded_exts: List[str] = [".pyc"]):

        # Execute command to create the remote directory
        self.execute_command(f"mkdir -p {remote_path}")

        if os.path.isfile(filepath):
            self.upload_file(filepath, remote_path, excluded_exts)
        else:
        
            try:
                # Traverse the directory tree
                for dirpath, _, filenames in os.walk(filepath):

                    remote_dirpath = os.path.join(remote_path, dirpath)

                    # Create remote directories if they don't exist
                    self.execute_command(f"mkdir -p {remote_dirpath}")

                    # Iterate through files
                    for filename in filenames:
                        local_path = os.path.join(dirpath, filename)
                        # Upload the file
                        self.upload_file(local_path, remote_dirpath, excluded_exts)
                      
                logging.info(
                    f"Finished uploading {filepath} files to {remote_path} on {self.host}"
                )

            except Exception as e:
                logging.error(f"Unexpected exception during bulk upload: {e}")

    def upload(self, filepaths: List[str], remote_path: str, excluded_exts: List[str] = [".pyc"]):

        if not isinstance(filepaths, list):
            filepaths = [filepaths]

        for filepath in filepaths:
            self._upload(filepath, remote_path, excluded_exts)

    def download_file(self, remote_filepath: str, local_path: str):

        os.makedirs(local_path, exist_ok=True)

        self.scp.get(remote_filepath, local_path=local_path, recursive=True)

    def execute_command(
        self,
        command: str,
        stream: bool = False,
        suppress: bool = False,
        ignore_output: bool = False,
        timeout: int = None,
    ):

        stdin, stdout, stderr = self.connection.exec_command(command, get_pty=True)

        if ignore_output:
            return

        stdout._set_mode('rb')

        last_recieved = time.time()

        if stream:
            
            response = ""

            for line in iter(stdout.readline, ""):
                
                if timeout is not None and (time.time() - last_recieved > timeout):
                    break

                if line == b"": # finsihed
                    break
                try:
                    line = line.decode("utf-8")
                except Exception as e:
                    line = ""

                if not suppress: print(line, end="")
                response += line

                last_recieved = time.time()

            response = None
                        
        else:

            stdout.channel.recv_exit_status()
            response = ""
            for line in stdout.readlines():

                if timeout is not None and (time.time() - last_recieved > timeout):
                    break

                if line == b"": # finsihed
                    break
                try:
                    line = line.decode("utf-8")
                except Exception as e:
                    line = ""

                response += line
                if not suppress: print(line)

                last_recieved = time.time()

        stderr.channel.recv_exit_status()
        for line in stderr.readlines():
            print(line)

        return response

class Reacher(object):

    ARTIFACATS_PATH = "artifacts"
    LOGS_PATH = "logs"

    WORKSPACE_PATH = "~/.reacher"
    BUILD_PATH = ""

    EXCLUDES = [
        ".git",
        ".__pycache__",
        "logs",
    ]

    def __init__(
        self,
        build_name: str,
        client: RemoteClient = None,
        host: str = None,
        port: int = 22,
        user: str = None,
        password: str = None,
        ssh_key_filepath: str = None,
        prefix_cmd: str = None,
    ):

        if client is None:

            assert (
                host is not None
                and user is not None
                and ssh_key_filepath is not None
            )

            client = RemoteClient(
                host=host,
                user=user,
                password=password,
                ssh_key_filepath=ssh_key_filepath,
                port=port,
            )

        self._client = client
    
        self._port_forwarding = PortForwarding(client=self._client)

        self._prefix_cmd = prefix_cmd

        self._build_name = build_name
    
    @property
    def workspace_path(self):

        return os.path.join("/home", self._client.user, ".reacher")
    
    def add_port_forward(self, remote_port: int, local_port: int, paramiko: bool = True):
        
        self._port_forwarding.add_port_forward(remote_port, local_port, paramiko)

    @property
    def build_path(self):

        return os.path.join(self.workspace_path, self._build_name)

    @property
    def log_path(self):

        return os.path.join(
            self.workspace_path,
            self._build_name,
            Reacher.LOGS_PATH
        )

    @property
    def artifact_path(self):

        return os.path.join(
            self.workspace_path,
            self._build_name,
            Reacher.ARTIFACATS_PATH
        )

    def setup(self):

        self._client.execute_command(
            f"mkdir -p {self.build_path} && mkdir -p {self.artifact_path} && mkdir -p {self.log_path}"
        )

    def cleanup(self, exclude: list = ["artifacts", "logs"]):

        files = self.ls()
        files_pruned = []

        for x in files:
            if any([f in x for f in exclude]):
                continue
            if x == "" or x == "." or x == "..":
                continue
            files_pruned.append(x)

        if len(files_pruned) > 0:
            cmd = f"rm -r {' '.join(files_pruned)}"
            self.execute_command(cmd, suppress=True)

        self.setup()

    def ls(self, folder: str = None):

        if folder is None:
            folder = self.build_path
        else:
            folder = os.path.join(self.build_path, folder)

        r = self.execute_command(
            f"find {folder} -mindepth 1 -print",
            suppress=True,
            stream=False,
        ).replace("\n", "").split("\r")

        r = [x for x in r if x != "" and x != "."]

        return r

    def put(self, path: str, destination_folder: str = None, excluded_exts: list = [".pyc"]):
        
        if destination_folder is None:
            destination_folder = self.build_path
        else:
            destination_folder = os.path.join(self.build_path, destination_folder)

        if not isinstance(path, list):
            path = [path]

        for p in path:
            self._client.upload(p, destination_folder, excluded_exts=excluded_exts)

        # make sure all files are owned by the user
        self._client.execute_command(
            f"find {self.build_path}" + " -user $(whoami) -exec chmod 777 {} \;",
            stream=False,
            suppress=False,
        )

    def get(self, path: Union[List[str], str], destination_folder: str = None):

        if destination_folder is None:
            destination_folder = "."

        if not isinstance(path, list):
            path = [path]

        for p in path:
            self._client.download_file(os.path.join(self.build_path, p), destination_folder)

    @property
    def artifacts(self):
        self.ls(self.artifact_path)

    def get_artifact(self, artifact: str, destination: str = None):
        self.get(os.path.join(self.artifact_path, artifact), destination)

    def put_artifact(self, artifact: str):
        self.put(artifact, self.artifact_path)

    def _wrap_command_in_screen(self, command: str, named_session: str = None):

        named_session = named_session if named_session is not None else uuid.uuid4()

        return f"screen -S {named_session} {command}"
    
    def _wrap_command_in_prefix(self, command: str):
        
        return f"{self._prefix_cmd};{command}"
    
    def execute(
        self,
        command: str,
        context: Union[str, List[str]] = None,
        named_session: str = None,
        cleanup_before: bool = False,
        wrap_in_screen: bool = True,
        excluded_exts: list = [".pyc"],
    ):  

        if cleanup_before:
            self.cleanup()

        if context is not None:
            self._client.upload(context, self.build_path, excluded_exts)

        self.execute_command(
            command,
            named_session=named_session,
            wrap_in_screen=wrap_in_screen
        )


    def execute_command(
        self,
        command,
        stream: bool = True,
        suppress: bool = False,
        named_session: str = None,
        wrap_in_screen: bool = False,
        ignore_output: bool = False,
        timeout: int = None,
    ):  

        if wrap_in_screen:
            command = self._wrap_command_in_screen(command, named_session=named_session)

        if self._prefix_cmd is not None:
            command = self._wrap_command_in_prefix(command)

        command = f"cd {self.build_path} && {command}"

        return self._client.execute_command(
            command,
            stream=stream,
            suppress=suppress,
            ignore_output=ignore_output,
            timeout=timeout,
        )
    
    def list_named_sessions(self):

        self.execute_command(f"screen -list")

    def attach_named_session(self, named_session: str):

        self.execute_command(f"screen -r -d {named_session}")

    def kill_named_session(self, named_session: str):

        self.execute_command(f"screen -X -S {named_session} quit")

class ReacherDocker(Reacher):

    CON_WORKSPACE_PATH = "/workspace"

    MOUNTED = [
        Reacher.ARTIFACATS_PATH,
        Reacher.LOGS_PATH, 
    ]

    def __init__(
        self,
        build_name: str,
        image_name: str,
        build_context: str,
        client: RemoteClient = None,
        host: str = None,
        port: int = 22,
        user: str = None,
        password: str = None,
        ssh_key_filepath: str = None
    ):

        super().__init__(
            build_name=build_name,
            client=client,
            host=host,
            port=port,
            user=user,
            password=password,
            ssh_key_filepath=ssh_key_filepath
        )

        self._image_name = image_name
        self._build_context = build_context 

    def _setup_remote(self):

        super().setup()

        self._client.upload(
            self._build_context,
            self.build_path,
        )

    def clear(self):

        if self.is_running:
            self._client.execute_command(
                f"docker stop {self._build_name}", suppress=True,
            )

        if self.exists:
            self._client.execute_command(
                f"docker rm {self._build_name}", suppress=True,
            )

    def ls(self, folder: str = None):

        if folder is None:
            folder = "."

        r = self.execute_command(
            f"find {folder} -mindepth 1 -print",
            suppress=True,
            stream=False,
        ).replace("\n", "").split("\r")

        r = [x for x in r if x != "" and x != "."]

        return r

    def build(self):

        self.clear()

        self._setup_remote()

        self._client.execute_command(
            f"docker build -t {self._build_name} {os.path.join(self.build_path, self._build_context)}",
            stream=True,
        )

    def execute_command(
        self,
        command,
        stream: bool = True,
        suppress: bool = False,
        named_session: str = None,
        wrap_in_screen: bool = False,
        ignore_output: bool = False,
    ):  

        if wrap_in_screen or named_session is not None:
            command = self._wrap_command_in_screen(command, named_session=named_session)

        command = f"docker exec -it {self._build_name} {command}"

        return self._client.execute_command(
            command,
            stream=stream,
            suppress=suppress,
            ignore_output=ignore_output,
        )

    def setup(
        self,
        ports: List[int] = None,
        envs: Dict[str, str] = None,
        command: str = "sleep infinity",
        gpu: bool = False,
    ):

        self.clear()

        extra_args = ""

        if gpu:
            extra_args = "--runtime=nvidia --gpus all"

        ctx = f"docker run -dt {extra_args} -w {ReacherDocker.CON_WORKSPACE_PATH} --name {self._build_name}"

        ctx = f"{ctx} -v {self.build_path}:{ReacherDocker.CON_WORKSPACE_PATH}"

        if ports is not None:
            for p in ports:
                ctx = f"{ctx} -p {p}:{p}"

        if envs is not None:
            for k, v in envs.items():
                ctx = f"{ctx} -e {k}={v}"

        ctx = f"{ctx} {self._image_name} {command}"

        self._client.execute_command(ctx)

        # Install screen in container
        self.execute_command(
            "apt-get -y install screen",
            wrap_in_screen=False,
        )

    @property
    def is_running(self):

        r = self._client.execute_command(
                'docker ps --format {{.Names}}', suppress=True,
        ).replace("\r", "").split("\n")

        return self._build_name in r

    @property
    def exists(self):

        r = self._client.execute_command(
                'docker ps -a --format {{.Names}}', suppress=True,
        ).replace("\r", "").split("\n")

        return self._build_name in r

    if __name__ == "__main__":

        pass

class ForwardServer(SocketServer.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

class Handler(SocketServer.BaseRequestHandler):
    
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel(
                "direct-tcpip",
                (self.chain_host, self.chain_port),
                self.request.getpeername(),
            )
        except Exception as e:
            print(
                "Incoming request to %s:%d failed: %s"
                % (self.chain_host, self.chain_port, repr(e))
            )
            return
        if chan is None:
            print(
                "Incoming request to %s:%d was rejected by the SSH server."
                % (self.chain_host, self.chain_port)
            )
            return

        print(
            "Connected!  Tunnel open %r -> %r -> %r"
            % (
                self.request.getpeername(),
                chan.getpeername(),
                (self.chain_host, self.chain_port),
            )
        )
        while True:
            r, w, x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                self.request.send(data)

        peername = self.request.getpeername()
        chan.close()
        self.request.close()
        print("Tunnel closed from %r" % (peername,))

def forward_tunnel(local_port, remote_host, remote_port, transport):

    class SubHander(Handler):
        chain_host = remote_host
        chain_port = remote_port
        ssh_transport = transport

    ForwardServer(("", local_port), SubHander).serve_forever()
    

def forward_tunnel_system(
        local_port,
        remote_port,
        client,
):  

    command = f"ssh -o StrictHostKeyChecking=no -i {client.ssh_key_filepath} -L 0.0.0.0:{local_port}:localhost:{remote_port} -N {client.user}@{client.host} -p {client.port}"
    
    os.system(command)
    
import threading
    
class PortForwarding(object):
    
    def __init__(
        self,
        host: str = None,
        user: str = None,
        ssh_port: int = 22,
        ssh_key_file_path: str = None,
        password: str = None,
        client: RemoteClient = None,
    ):
        
        if client is None:
        
            self._client = RemoteClient(
                host=host,
                user=user,
                password=password,
                ssh_key_file_path=ssh_key_file_path,
                port=ssh_port,
            )
            
        else:
            
            self._client = client

        self._threads = []
    
    def add_port_forward(self, remote_port: int, local_port: int, paramiko: bool = True):
        
        if paramiko:

            transport = self._client.connection.get_transport()
        
            x = threading.Thread(
                target=forward_tunnel,
                args=(local_port, self._client.host, remote_port, transport),
                daemon=True
            )

        else:
                
            x = threading.Thread(
                target=forward_tunnel_system,
                args=(local_port, remote_port, self._client),
                daemon=True
            )

        self._threads.append(x)
        
        self._threads[-1].start()


## Some helper functions for creating notebooks and tensorboards

def create_notebook(
    reacher: Reacher,
    remote_port: int,
    local_port: int,
    paramiko: bool = False
):

    import time 

    reacher.execute_command(
        f"jupyter notebook --ip 0.0.0.0 --allow-root --port {remote_port}",
        wrap_in_screen=True,
        named_session="notebook",
        ignore_output=True,
    )

    time.sleep(1)

    reacher.add_port_forward(remote_port=remote_port, local_port=local_port, paramiko=paramiko)

    r = reacher.execute_command("jupyter notebook list", stream=False, suppress=True)

    r = r.replace(str(remote_port), str(local_port))

    print(r)

def create_tensorboard(
    reacher: Reacher,
    remote_port: int,
    local_port: int,
    paramiko: bool = False,
    logdir: str = "artifacts"
):
    
    import time 
    
    reacher.execute_command(f"mkdir -p {logdir}")

    reacher.execute_command(
        f"tensorboard --host 0.0.0.0 --port {remote_port} --logdir {logdir}",
        wrap_in_screen=True,
        named_session="tensorboard",
        ignore_output=True,
    )

    time.sleep(1)

    reacher.add_port_forward(remote_port=remote_port, local_port=local_port, paramiko=paramiko)

    print(f"tensorboard running on\nhttp://0.0.0.0:{local_port}/")
