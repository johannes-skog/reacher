import os
from typing import List, Dict
import uuid
from os import system
from typing import List
import os
from paramiko import AutoAddPolicy, RSAKey, SSHClient
from paramiko.auth_handler import AuthenticationException, SSHException
from scp import SCPClient, SCPException
import logging
import shutil

class RemoteClient:
    """Client to interact with a remote host via SSH & SCP."""

    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        ssh_key_filepath: str,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.ssh_key_filepath = ssh_key_filepath
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
                timeout=5000,
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
        return SCPClient(conn.get_transport())

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

        file_name = remote_filepath.split("/")[-1]
        
        self.scp.get(remote_filepath)

        shutil.move(file_name, local_path)

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
            response = stdout.readlines()
            for line in response:
                if line == b"": # finsihed
                    break
                try:
                    line = line.decode("utf-8")
                except Exception as e:
                    line = ""
                if not suppress: print(line)
                
        stderr.channel.recv_exit_status()
        for line in stderr.readlines():
            print(line)

        return response


class Reacher(object):

    WORKSPACE_PATH = "~/.reacher"
    BUILD_PATH = ""

    CON_WORKSPACE_PATH = "/workspace"
    CON_ARTIFACATS_PATH = "artifacts"
    CON_LOGS_PATH = "logs"

    MOUNTED = [
        CON_ARTIFACATS_PATH,
        CON_LOGS_PATH
    ]

    def __init__(
        self,
        client: RemoteClient,
        build_name: str,
        image_name: str,
        build_context: str,
    ):

        self._client = client
        self._build_name = build_name
        self._image_name = image_name
        self._build_context = build_context 
    
    @property
    def workspace_path(self):

        return os.path.join("/home", self._client.user, ".reacher")

    @property
    def build_path(self):

        return os.path.join(self.workspace_path, self._build_name)

    @property
    def log_path(self):

        return os.path.join(
            self.workspace_path,
            self._build_name,
            Reacher.CON_LOGS_PATH
        )

    @property
    def artifact_path(self):

        return os.path.join(
            self.workspace_path,
            self._build_name,
            Reacher.CON_ARTIFACATS_PATH
        )

    def _setup_remote(self):

        self._client.execute_command(
            f"mkdir -p {self.build_path} && mkdir -p {self.artifact_path} && mkdir -p {self.log_path}"
        )

        self._client.upload_dir(
            self._build_context,
            self.build_path,
        )

    def clear(self):

        self._client.execute_command(
            f"rm -rf {self.build_path}", suppress=True,
        )

        if self.is_running:
            self._client.execute_command(
                f"docker stop {self._build_name}", suppress=True,
            )

        if self.exists:
            self._client.execute_command(
                f"docker rm {self._build_name}", suppress=True,
            )

        self._setup_remote()

    @property
    def artifacts(self):

        r = self._client.execute_command(
            f"ls {self.artifact_path}",
        )

        r = [x.strip("\n").strip("\r") for x in r]

        return r

    def get_artifact(self, artifact: str, destination: str = None):

        self._client.download_file(
            os.path.join(self.artifact_path, artifact),
            (
                destination if destination is not None else 
                os.path.join(".reacher", self._build_name, Reacher.CON_ARTIFACATS_PATH)
            )
        )

    def put_artifact(self, artifact: str):

        self._client.upload_dir(artifact, self.artifact_path)

    def get_all_artifact(self, destination: str = None):

        for artifact in self.artifacts:
            self.get_artifact(artifact, destination)

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
            named_session = named_session if named_session is not None else uuid.uuid4()
            command = f"screen -S {named_session} {command}"

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
        file: str = None,
        command: str = None,
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
        
        if file is not None:
            command = command if command is not None else f"python {file}"
        
        self.execute_command(command, named_session=named_session, wrap_in_screen=True)

    def list_named_sessions(self):

        self.execute_command(f"screen -list")

    def attach_named_session(self, named_session: str):

        self.execute_command(f"screen -r -d {named_session}")

    def kill_named_session(self, named_session: str):

        self.execute_command(f"screen -X -S {named_session} quit")

    def setup(
        self,
        ports: List[int] = None,
        envs: Dict[str, str] = None,
        command: str = "sleep infinity",
    ):

        self.clear()

        ctx = f"docker run -dt -w {Reacher.CON_WORKSPACE_PATH} --name {self._build_name}"

        ctx = f"{ctx} -v {self.artifact_path}:{Reacher.CON_WORKSPACE_PATH}/{Reacher.CON_ARTIFACATS_PATH}"
        ctx = f"{ctx} -v  {self.log_path}:{Reacher.CON_WORKSPACE_PATH}/{Reacher.CON_LOGS_PATH}"

        if ports is not None:
            for p in ports:
                ctx = f"{ctx} -p {p}:{p}"

        if envs is not None:
            for k, v in envs.items():
                ctx = f"{ctx} -e {k}={v}"

        path = os.path.join(self.build_path, self._build_context, "logging-driver-config.json")

        ctx = f"{ctx} {self._image_name} {command}"

        self._client.execute_command(ctx)

        # Install screen in container
        self.execute_command(
            "apt-get -y install screen",
            wrap_in_screen=False,
        )

    @property
    def is_running(self):

        r = " ".join(
            self._client.execute_command(
                'docker ps --format {{.Names}}', suppress=True,
            )
        ).strip("\n").strip("\r")

        return self._build_name in r

    @property
    def exists(self):

        r = " ".join(
            self._client.execute_command(
                'docker ps -a --format {{.Names}}', suppress=True,
            )
        ).strip("\n").strip("\r")

        return self._build_name in r

    if __name__ == "__main__":

        pass