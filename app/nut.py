"""Network UPS Tools (NUT) client over TCP (port 3493)."""
import asyncio
from typing import Optional


class NutClient:
    def __init__(self, host: str, port: int, ups_name: str,
                 username: str = "", password: str = ""):
        self.host     = host
        self.port     = int(port)
        self.ups_name = ups_name
        self.username = username
        self.password = password

    async def _connect(self):
        return await asyncio.open_connection(self.host, self.port)

    async def _cmd(self, reader: asyncio.StreamReader,
                   writer: asyncio.StreamWriter, cmd: str) -> str:
        writer.write((cmd + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5)
        return line.decode().strip()

    async def _session(self, commands: list[str]) -> list[str]:
        """Open a session, optionally authenticate, run commands, logout."""
        reader, writer = await asyncio.open_connection(self.host, self.port)
        responses: list[str] = []
        try:
            if self.username:
                await self._cmd(reader, writer, f"USERNAME {self.username}")
            if self.password:
                resp = await self._cmd(reader, writer, f"PASSWORD {self.password}")
                if resp.startswith("ERR"):
                    raise ValueError(f"NUT auth failed: {resp}")
            for cmd in commands:
                resp = await self._cmd(reader, writer, cmd)
                responses.append(resp)
            await self._cmd(reader, writer, "LOGOUT")
        finally:
            writer.close()
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=2)
            except Exception:
                pass
        return responses

    async def test(self) -> tuple[bool, str]:
        try:
            responses = await asyncio.wait_for(
                self._session([f"GET VAR {self.ups_name} ups.status"]),
                timeout=10,
            )
            r = responses[0] if responses else ""
            if r.startswith("ERR"):
                return False, r
            # VAR upsname ups.status "OL"
            val = r.split('"')[1] if '"' in r else r
            return True, f"Connected — {self.ups_name}: {val}"
        except asyncio.TimeoutError:
            return False, "Connection timed out"
        except ConnectionRefusedError:
            return False, f"Connection refused ({self.host}:{self.port})"
        except Exception as e:
            return False, str(e)

    async def get_status(self) -> tuple[bool, str]:
        """Read status, load %, and battery charge."""
        try:
            vars_to_read = [
                f"GET VAR {self.ups_name} ups.status",
                f"GET VAR {self.ups_name} ups.load",
                f"GET VAR {self.ups_name} battery.charge",
                f"GET VAR {self.ups_name} battery.runtime",
            ]
            responses = await asyncio.wait_for(
                self._session(vars_to_read),
                timeout=10,
            )

            def _val(line: str) -> str:
                return line.split('"')[1] if '"' in line else line.replace("ERR", "?")

            status  = _val(responses[0]) if len(responses) > 0 else "?"
            load    = _val(responses[1]) if len(responses) > 1 else "?"
            charge  = _val(responses[2]) if len(responses) > 2 else "?"
            runtime = _val(responses[3]) if len(responses) > 3 else "?"

            msg = f"status={status} load={load}% battery={charge}%"
            if runtime and runtime != "?":
                try:
                    mins = int(runtime) // 60
                    msg += f" runtime≈{mins}min"
                except ValueError:
                    pass
            return True, msg
        except asyncio.TimeoutError:
            return False, "Connection timed out"
        except Exception as e:
            return False, str(e)

    async def instcmd(self, command: str) -> tuple[bool, str]:
        """Send an instant command (e.g. beeper.disable, load.off)."""
        try:
            responses = await asyncio.wait_for(
                self._session([f"INSTCMD {self.ups_name} {command}"]),
                timeout=10,
            )
            r = responses[0] if responses else ""
            if r == "OK":
                return True, f"Command '{command}' sent to {self.ups_name}"
            return False, r or "No response"
        except asyncio.TimeoutError:
            return False, "Connection timed out"
        except Exception as e:
            return False, str(e)
