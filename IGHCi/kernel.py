import re

from itertools            import groupby
from functools            import reduce
from ipykernel.kernelbase import Kernel
from pexpect.replwrap     import REPLWrapper

class IGHCi(Kernel):
    implementation = 'Haskell'
    implementation_version = '0.1'
    language = 'haskell'
    language_version = '9.12.1'
    language_info = {
        'name': 'haskell',
        'mimetype': 'text/x-haskell',
        'file_extension': '.hs',
    }
    banner = "IGHCi kernel"
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._start_ghci()

    def _start_ghci(self):
        self.ghci = REPLWrapper(
            "ghci",
            orig_prompt = r"ghci> ",
            prompt_change = None,
            continuation_prompt = "ghci| ",
        )
        
    def _process_code(self, code):
        is_ghci_command = lambda line: line.strip().startswith(':')
        wrap_block      = lambda lines: ":{\n" + "\n".join(lines) + "\n:}"
        remove_markers  = lambda line: "" if line in {":{", ":}"} else line.replace(":{", "").replace(":}", "")
    
        process_non_commands = lambda lines: [
            wrap_block(block) if len(block) > 1 else block[0]
            for block in (
                list(block)
                for is_nonempty, block in groupby(lines, key = lambda l: l.strip() != '')
                if is_nonempty
            )
        ]
    
        lines  = map(remove_markers, code.splitlines())
        groups = groupby(lines, key = is_ghci_command)
        
        return [
            item
            for is_cmd, group in groups
            for item in (list(group) if is_cmd else process_non_commands(list(group)))
        ]

    _ansi_escape = re.compile(r'\x1b\[([0-9;]*)([A-Za-z])')
    _error_regex = re.compile(
        r'^\s*<interactive>:\d+:\d+:\s+error:|unrecognised flag:.*|unknown command.*',
        re.MULTILINE | re.IGNORECASE
    )
    
    def _process_output(self, output):
        clean    = self._ansi_escape.sub('', output)
        is_error = bool(self._error_regex.search(clean))
        text     = output.strip() if is_error else output
        return is_error, text

    # Function renaming?
    def _send_output(self, stream, text):
        self.send_response(self.iopub_socket, 'stream', {'name': stream, 'text': text})
    
    def _execute_command(self, cmd): 
        is_prompt_change_command = any(
            self._prompt_regex.search(line)
            for line in map(str.strip, cmd.splitlines())
            if line.startswith(':set')
        )

        if is_prompt_change_command:
            self._send_output("stderr", "Changing GHCi prompts is not allowed.")
            return 'error'
        try:
            output         = self.ghci.run_command(cmd)     
            is_error, text = self._process_output(output)
        
            stream = 'stderr' if is_error else 'stdout'
            status = 'error' if is_error else 'ok'
            
            self._send_output(stream, text)
            return status
        except KeyboardInterrupt:
            # TODO: handling large outputs after interruption,
            # like factorial of 65000
            self.ghci.child.sendintr()
            output_intr = self.ghci.child.before
            self._send_output("stderr", f"Interrupted:\n{output_intr}")            
            return 'abort'
        except Exception as e:
            self.log.error(str(e))
            self._send_output("stderr", str(e))
            return 'error'

        return self._process_output(output)

    # TODO: Better regexps I guess?
    # v_promptXYZ = 42 => error
    _prompt_regex = re.compile(r'(prompt|prompt-cont)')
    _stdin_regex  = re.compile(r'(getChar|getLine|getContents|interact)')

    def _early_check(self, code):    
        if not code:
            return 'ok'
            
        rules = [
            (self._stdin_regex, "Functions dealing with stdin are not currently supported."),
            (self._prompt_regex, "Changing GHCi prompts is not allowed.")
        ]
        
        matchings = [message for regex, message in rules if re.findall(regex, code)]

        if matchings:
            for msg in matchings:
                self._send_output('stderr', msg)
                return 'error'
        return None
    
    def do_execute(self, code, silent, 
                   store_history    = True,
                   user_expressions = None,
                   allow_stdin      = False):
        return_response = lambda status: {'status': status, 'execution_count': self.execution_count}
        
        if early_status := self._early_check(code):
            return return_response(early_status)
        
        processed_code = self._process_code(code)
        
        status = reduce(
            lambda acc, cmd: acc if acc in {'error', 'abort'} else self._execute_command(cmd),
            processed_code,
            'ok'
        )

        return return_response(status)

    def do_shutdown(self, restart):
        self.ghci.child.close()
        return {"status": "ok", "restart": restart}
