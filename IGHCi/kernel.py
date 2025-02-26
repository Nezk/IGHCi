import re
import json

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
            "ghci -fdiagnostics-as-json",
            orig_prompt = r"ghci> ",
            prompt_change = None,
            continuation_prompt = "ghci| ",
        )
        
    def _process_code(self, code):
        is_ghci_command = lambda line: line.strip().startswith(':')
        wrap_block      = lambda lines: ":{\n" + "\n".join(lines) + "\n:}"
            
        process_non_commands = lambda lines: [
            wrap_block(block) if len(block) > 1 else block[0]
            for block in (
                list(block)
                for is_nonempty, block in groupby(lines, key = lambda l: l.strip() != '')
                if is_nonempty
            )
        ]
        
        wo_ml_comments = re.sub(r'\{-(.*?)\-\}', '', code, flags = re.DOTALL)
        wo_sl_comments = re.sub(r'--.*', '', wo_ml_comments)
        wo_bl          = re.sub(r'^\s*:(?:\{|\})\s*$', '', wo_sl_comments, flags = re.MULTILINE)
    
        lines  = wo_bl.splitlines()
        groups = groupby(lines, key = is_ghci_command)
            
        return [
            item
            for is_cmd, group in groups
            for item in (list(group) if is_cmd else process_non_commands(list(group)))
        ]

    _error_regex = re.compile(r'(?xs)'
                              r'^\s*\{'
                              r'(?=.*["\']severity["\']\s*:\s*["\']Error["\'])'
                              r'.*\}\s*$'
                             )
    _warning_regex = re.compile(r'(?xs)'
                                r'^\s*\{'
                                r'(?=.*["\']severity["\']\s*:\s*["\']Warning["\'])'
                                r'.*\}\s*$'
                             )
    _exception_regex = re.compile(r'\*\*\* Exception:')

    
    def _process_output(self, output):

        def pformat_stderr(error):
            severity = error.get('severity', None)
            
            if severity:
                severity_info = f"[{severity}] "
            else:
                severity_info = ''
            
            message = '\n'.join(error.get('message', []))
            span = error.get('span', None)
            
            if span:
                file = span.get('file', '<unknown file>')
                
                start = span.get('start', {})
                end   = span.get('end', {})
                
                start_line   = start.get('line', '?')
                start_column = start.get('column', '?')
                
                end_line   = end.get('line', '?')
                end_column = end.get('column', '?')
                
                span_info = f"{file} {start_line}:{start_column}—{end_line}:{end_column}\n\n"
            else:
                span_info = ''
                
            formatted_output = f"{severity_info}{span_info}{message}"
            
            return formatted_output
        
        is_error     = bool(self._error_regex.search(output))
        is_warning   = bool(self._warning_regex.search(output))
        is_exception = bool(self._exception_regex.search(output))
        
        is_ok        = not (is_error or is_exception)
        is_to_stderr = is_error or is_warning or is_exception

        stripped = output.strip()
        is_html  = (not is_to_stderr) and stripped.startswith('<html>') and stripped.endswith('</html>')
        
        if is_error or is_warning:
            errors    = [json.loads(error) for error in output.split("\r\n") if error]
            pp_errors = [pformat_stderr(error) for error in errors]
            
            processed_text = "\n\n".join(pp_errors)
        if is_exception:
            processed_text = stripped
        if is_html:
            html_content   = stripped[len('<html>'):-len('</html>')]
            processed_text = html_content.strip()
        if not (is_error or is_warning or is_exception or is_html):
            processed_text = output
        
        return is_ok, is_to_stderr, is_html, processed_text

    def _execute_command(self, cmd): 
        try:
            output = self.ghci.run_command(cmd)

            if not output: 
                return 'ok'

            is_ok, is_to_stderr, is_html, text = self._process_output(output)

            if is_html:
                # TODO: Figure out how mixed output works, 
                # i.e. how Jupyter works when one cell outputs both text (stdout) and HTML in one cell
                self.send_response(
                    self.iopub_socket,
                    'display_data',
                    {
                        'data': {'text/html': text},
                        'metadata': {}
                    }
                )
                # Guaranteed by `not is_to_stderr …`
                status = 'ok'
            else:
                stream = 'stderr' if is_to_stderr else 'stdout'
                status = 'ok'     if is_ok        else 'error'
                self.send_response(self.iopub_socket, 
                                   'stream', 
                                   {'name': stream,
                                    'text': text})
            return status
        except KeyboardInterrupt:
            self.ghci.child.sendintr()
            output_intr = self.ghci.child.before
            output_intr_formatted = f"Interrupted:\n{output_intr}"
            self.log.error(output_intr_formatted)
            self.send_response(self.iopub_socket, 
                               'stream', 
                               {'name': "stderr",
                                'text': output_intr_formatted})
            return 'abort'
        except Exception as e:
            exception_formatted = str(e)
            self.log.error(exception_formatted)
            self.send_response(self.iopub_socket, 
                               'stream', 
                               {'name': "stderr",
                                'text': exception_formatted})
            return 'error'

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
                self.send_response(self.iopub_socket, 
                                   'stream', 
                                   {'name': "stderr",
                                    'text': msg})
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