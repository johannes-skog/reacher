
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
import shutil
import socket
import select
import sys

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

    def upload_dir(self, filepath: str, remote_path: str):
        
        self.execute_command(f"mkdir -p {remote_path}")
        
        try:
            self.scp.put(filepath, remote_path=remote_path, recursive=True)
            logging.info(
                f"Finished uploading {filepath} files to {remote_path} on {self.host}"
            )
        except SCPException as e:
            logging.error(f"SCPException during bulk upload: {e}")
        except Exception as e:
            logging.error(f"Unexpected exception during bulk upload: {e}")

    def download_file(self, remote_filepath: str, local_path: str):

        os.makedirs(local_path, exist_ok=True)

        self.scp.get(remote_filepath, local_path=local_path, recursive=True)

    def execute_command(self, command: str, stream: bool = False, suppress: bool = False):

        stdin, stdout, stderr = self.connection.exec_command(command, get_pty=True)

        stdout._set_mode('rb')

        if stream:
            
            response = ""

            for line in iter(stdout.readline, ""):
                if line == b"": # finsihed
                    break
                try:
                    line = line.decode("utf-8")
                except Exception as e:
                    line = ""

                if not suppress: print(line, end="")
                response += line

            response = None
                        
        else:

            stdout.channel.recv_exit_status()
            response = ""
            for line in stdout.readlines():
                if line == b"": # finsihed
                    break
                try:
                    line = line.decode("utf-8")
                except Exception as e:
                    line = ""

                response += line
                if not suppress: print(line)

        stderr.channel.recv_exit_status()
        for line in stderr.readlines():
            print(line)

        return response

class Reacher(object):

    ARTIFACATS_PATH = "artifacts"
    LOGS_PATH = "logs"

    WORKSPACE_PATH = "~/.reacher"
    BUILD_PATH = ""

    def __init__(
        self,
        build_name: str,
        client: RemoteClient = None,
        host: str = None,
        port: int = 22,
        user: str = None,
        password: str = None,
        ssh_key_filepath: str = None
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

    def clear(self):

        self._client.execute_command(
            f"rm -rf {self.build_path}", suppress=True,
        )

        self.setup()

    def ls(self, folder: str = None):

        if folder is None:
            folder = self.build_path
        else:
            folder = os.path.join(self.build_path, folder)

        r = self._client.execute_command(
            f"find {folder} -print",
            suppress=False,
        )

    def put(self, path: str, destination_folder: str = None):
        
        if destination_folder is None:
            destination_folder = self.build_path
        else:
            destination_folder = os.path.join(self.build_path, destination_folder)

        if not isinstance(path, list):
            path = [path]

        for p in path:
            self._client.upload_dir(p, destination_folder)

    def get(self, path: Union[List[str], str], destination_folder: str = None):

        if destination_folder is None:
            destination_folder = os.path.join(".reacher", self._build_name)

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

    def execute_command(
        self,
        command,
        stream: bool = True,
        suppress: bool = False,
        named_session: str = None,
        wrap_in_screen: bool = False,
    ):  

        if wrap_in_screen:
            command = self._wrap_command_in_screen(command, named_session=named_session)

        command = f"cd {self.build_path} && {command}"

        return self._client.execute_command(
            command,
            stream=stream,
            suppress=suppress,
        )

    def execute(
        self,
        command: str,
        file: str = None,
        context_folder: str = None,
        named_session: str = None,
    ):  

        if file is not None:
            self._client.upload_dir(file, self.build_path)
        if context_folder is not None:
            e = context_folder.split("/")[-1]
            intermidiate = os.path.join(self.build_path, "trash0")
            self._client.upload_dir(context_folder, intermidiate)
            self.execute_command(
                f"mv {intermidiate}/{e}/* {self.build_path} && rm -r {intermidiate}",
                wrap_in_screen=False,
            )

        self.execute_command(
            command,
            named_session=named_session,
            wrap_in_screen=True,
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
        Reacher.LOGS_PATH
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

        super()._setup_remote()

        self._client.upload_dir(
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

        super().clear()

    def build(self):

        self.clear()

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
    ):  

        if wrap_in_screen or named_session is not None:
            command = self._wrap_command_in_screen(command, named_session=named_session)

        command = f"docker exec -it {self._build_name} {command}"

        return self._client.execute_command(
            command,
            stream=stream,
            suppress=suppress,
        )

    def _clear_container(self):

        ls = self.execute_command("ls", stream=False, suppress=True)

        ls = " ".join(ls).split()   

        ls = [
            x.strip('\n').strip('\r').replace("\t", '') for x in ls
        ]

        ls = [
            x for x in ls if (x not in Reacher.MOUNTED)
        ]

        if len(ls) > 0:
            cmd = f"rm -r {' '.join(ls)}"
            self.execute_command(cmd)

    def execute(
        self,
        command: str,
        file: str = None,
        context_folder: str = None,
        named_session: str = None,
        clear_container: bool = False,
    ):  

        if clear_container:
            self._clear_container()

        tmp_path = os.path.join(self.build_path, "src")
        self._client.execute_command(f"mkdir -p {tmp_path}")

        if file is not None:
            self._client.upload_dir(file, tmp_path)
        
        if context_folder is not None:
            e = context_folder.split("/")[-1]
            intermidiate = os.path.join(self.build_path, "trash0")
            self._client.upload_dir(context_folder, intermidiate)
            self._client.execute_command(
                f"mv {intermidiate}/{e}/* {tmp_path} && rm -r {intermidiate}"
            )

        self._client.execute_command(
            f"docker cp {tmp_path}/. {self._build_name}:/{Reacher.CON_WORKSPACE_PATH}"
        )

        self._client.execute_command(f"rm -r {tmp_path}")

        self.execute_command(
            command,
            named_session=named_session,
            wrap_in_screen=True
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

        ctx = f"docker run -dt {extra_args} -w {Reacher.CON_WORKSPACE_PATH} --name {self._build_name}"

        ctx = f"{ctx} -v {self.artifact_path}:{Reacher.CON_WORKSPACE_PATH}/{Reacher.ARTIFACATS_PATH}"
        ctx = f"{ctx} -v  {self.log_path}:{Reacher.CON_WORKSPACE_PATH}/{Reacher.LOGS_PATH}"

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

    command = f"ssh -L {local_port}:localhost:{remote_port} -N {client.user}@{client.host} -p {client.port}"
    
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