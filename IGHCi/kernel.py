import re
import os
import json
import tempfile
import shutil

from itertools            import groupby, chain
from functools            import reduce
from ipykernel.kernelbase import Kernel
from pexpect.replwrap     import REPLWrapper

class IGHCi(Kernel):
    implementation         = 'Haskell'
    implementation_version = '0.0.2'
    language               = 'haskell'

    language_info = {
        'name':           'haskell',
        'mimetype':       'text/x-haskell',
        'file_extension': '.hs',
    }

    banner = "IGHCi kernel"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create a temporary directory for storing module files for this kernel session
        self._module_path = tempfile.mkdtemp()
        self._start_ghci()

    def _start_ghci(self):
        # TODO: Generate a random prompt using pexpect’s built-in mechanisms, or getting rid of pexpect entirely.
        self.ghci = REPLWrapper(
            # -fdiagnostics-as-json is supported only for GHC >= 9.10
            f"ghc --interactive -ignore-dot-ghci -fdiagnostics-as-json -i{self._module_path}",
            orig_prompt         = r"ghci> ",
            prompt_change       = None,
            continuation_prompt = "ghci| ",
        )

    _clean_code_regex = re.compile(r'^\s*:(?:\{|\})\s*$', flags = re.MULTILINE)

    def _process_code(self, code):
        is_ghci_command = lambda line: line.startswith(':')
        wrap_block      = lambda lines: ":{\n" + "\n".join(lines) + "\n:}"

        cleaned = self._clean_code_regex.sub('', code)
        lines   = cleaned.strip().splitlines()

        groups = groupby(lines, key = is_ghci_command)

        processed = [
            item if is_cmd else [wrap_block(item)]
            for is_cmd, group in groups
            for item in [list(group)]
        ]

        return list(chain.from_iterable(processed))

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
            span    = error.get('span', None)

            if span:
                file  = span.get('file', '<unknown file>')
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

        process_stderr = lambda to_stderr: "\n\n".join(map(pformat_stderr, to_stderr))

        lines       = output.splitlines()
        match_lines = lambda regex: [json.loads(line) for line in lines if regex.match(line)]

        if errors := match_lines(self._error_regex):
            processed_errors = process_stderr(errors)
            return ("errors", processed_errors)

        if warnings := match_lines(self._warning_regex):
            processed_warnings = process_stderr(warnings)
        else:
            processed_warnings = None

        result_lines = [line for line in lines if not self._warning_regex.match(line)]
        result       = "\n".join(result_lines).strip()

        # I. e. result is exception
        if any(self._exception_regex.match(line) for line in result_lines):
            # Adding newlines for separating exception from previous warnings
            processed_exception = f"\n\n{result}" if warnings else result
            return ("exceptions", processed_exception, processed_warnings)

        # TODO: Split a single output containing multiple `<html>` wrappers into separate messages.
        if result.startswith('<html>') and result.endswith('</html>'):
            processed_html = result[len('<html>'):-len('</html>')].strip()
            return ("html", processed_html, processed_warnings)

        return ("result", result, processed_warnings)

    def _send_output(self, output):

        if not output: 
            return 'ok'

        processed_output = self._process_output(output)

        # I used dataclasses previously but didn't like it
        if not processed_output[0] == "errors":
            if warnings := processed_output[-1]:
                self.send_response(self.iopub_socket, 'stream', {'name': 'stderr', 'text': warnings})

        match processed_output:
            case ("errors", errors):
                self.send_response(self.iopub_socket, 'stream', {'name': 'stderr', 'text': errors})
                return 'error'
            case ("exceptions", exceptions, _):
                self.send_response(self.iopub_socket, 'stream', {'name': 'stderr', 'text': exceptions})
                return 'error'
            case ("html", html, _):
                self.send_response(self.iopub_socket, 'display_data', {'data': {'text/html': html}, 'metadata': {}})
                return 'ok'
            case ("result", result, _):
                self.send_response(self.iopub_socket, 'stream', {'name': 'stdout', 'text': result})
                return 'ok'

        return 'error' # Should be unreachable

    _quit_regex   = re.compile(r'^\s*:q\w*\s*$', re.MULTILINE)
    _prompt_regex = re.compile(r'^\s*:set\s+prompt(?!-function)', re.MULTILINE)
    # Not exhaustive by any means
    _stdin_regex  = re.compile(r'\b(getChar|getLine|getContents|interact|hGetLine|hGetContents|hGetContents|hGetChar)\b')

    def _early_check(self, code):
        if not code:
            return 'ok'

        rules = [
            (self._quit_regex,   "Do not use the :quit command to shut down the kernel."),
            (self._stdin_regex,  "Functions dealing with stdin are not currently supported."),
            (self._prompt_regex, "Changing GHCi prompts is not allowed.")
        ]

        if matchings := [message for regex, message in rules if re.findall(regex, code)]:
            matching_msg = "\n".join(matchings)
            self.send_response(self.iopub_socket, 'stream', {'name': "stderr", 'text': matching_msg})
            return 'error'
        return None

    _module_regex = re.compile(
        r'^.*?^\s*module\s+((?:[A-Z][\w\']*\.)*)([A-Z][\w\']*)\b',
        flags=re.DOTALL | re.MULTILINE
    )

    def _load_module(self, module_match, code):
        path_raw, module_name = module_match.groups()

        # Determine module path components for hierarchical modules
        path_components = path_raw.split('.')[:-1] if path_raw else []
        module_dir      = os.path.join(self._module_path, *path_components)

        os.makedirs(module_dir, exist_ok = True)

        filename = os.path.join(module_dir, f"{module_name}.hs")

        with open(filename, 'w') as f:
            f.write(code)

        try:
            cmd = f":l {filename}"
            output = self.ghci.run_command(cmd)
            return self._send_output(output)
        except Exception as e:
            self.send_response(self.iopub_socket, 'stream', {
                'name': 'stderr',
                'text': f"Error handling module: {str(e)}"
            })
            return 'error'

    def _execute_code(self, code): 
        try:
            output = self.ghci.run_command(code)
            return self._send_output(output)
        except KeyboardInterrupt:
            # TODO: handling warnings after interruption?
            self.ghci.child.sendintr()

            # Wait for the prompt after interruption
            self.ghci.child.expect(self.ghci.prompt)
            output_intr = self.ghci.child.before

            if output_intr.strip():
                output_intr_formatted = f"Interrupted:\n{output_intr}"
                self.send_response(self.iopub_socket, 'stream', {'name': "stderr", 'text': output_intr_formatted})

            return 'abort'
        except Exception as e:
            exception_formatted = str(e)
            self.log.error(exception_formatted)
            self.send_response(self.iopub_socket, 'stream', {'name': "stderr", 'text': exception_formatted})
            return 'error'

    def do_execute(self, code, silent, 
                   store_history    = True,
                   user_expressions = None,
                   allow_stdin      = False):

        return_response = lambda status: {'status': status, 'execution_count': self.execution_count}

        if early_status := self._early_check(code):
            return return_response(early_status)

        if module_match := self._module_regex.search(code):
            return return_response(self._load_module(module_match, code))

        processed_code = self._process_code(code)

        status = reduce(
            lambda acc, code: acc if acc in {'error', 'abort'} else self._execute_code(code),
            processed_code,
            'ok'
        )

        return return_response(status)

    def do_shutdown(self, restart):
        self.ghci.child.close()
        # Clean up the temporary directory on shutdown
        shutil.rmtree(self._module_path)
        return {"status": "ok", "restart": restart}

    # I don't think there is any need in greek alphabet
    _LATEX_COMPLETIONS = {
         '\\::': '∷', '\\=>': '⇒', '\\->': '→', '\\<-': '←', '\\r': '→',
         '\\u': '↑', '\\d': '↓', '\\>-': '⤚', '\\-<': '⤙', '\\>>-': '⤜',
         '\\-<<': '⤛', '\\*': '★', '\\forall': '∀', '\\in': '∈', '\\(|': '⦇',
         '\\|)': '⦈', '\\[|': '⟦', '\\|]': '⟧', '\\%1->': '⊸', '\\-o': '⊸',
         '\\o': '∘',
    }

    # TODO: Investigate bug where completions for expressions like `(pure 3) >>`
    # and other operators beginning with `>` or `<` are not displayed.
    def do_complete(self, code, cursor_pos):
        # TODO: function for returning dict with 'status' and so on

        line_start        = code.rfind('\n', 0, cursor_pos) + 1
        current_line_part = code[line_start:cursor_pos]

        latex_pattern = re.compile(r'(\\\S*)$')
        latex_match   = latex_pattern.search(current_line_part)
        if latex_match:
            token = latex_match.group(1)

            latex_suggestions = [self._LATEX_COMPLETIONS[key] 
                                 for key in self._LATEX_COMPLETIONS 
                                 if key.startswith(token)]
            if latex_suggestions:
                token_start = code.rfind(token, 0, cursor_pos)
                return {
                    'status':       'ok',
                    'matches':      latex_suggestions,
                    'cursor_start': token_start,
                    'cursor_end':   cursor_pos,
                    'metadata':     {}
                }

        try:
            current_line = code[line_start:cursor_pos]
            ghci_cmd     = f":complete repl \"{current_line}\""
            output       = self.ghci.run_command(ghci_cmd)
        except Exception as e:
            return {
                'status':       'error',
                'matches':      [],
                'cursor_start': cursor_pos,
                'cursor_end':   cursor_pos,
                'metadata':     {'error': str(e)}
            }

        lines  = output.splitlines()
        header = lines[0].split(" ", 2)

        if header[0] == '0' or header[1] == '0':
            return {
                'status':       'ok',
                'matches':      [],
                'cursor_start': cursor_pos,
                'cursor_end':   cursor_pos,
                'metadata':     {}
            }

        prefix      = header[-1][1:-1]
        suggestions = [suggestion[1:-1] for suggestion in lines[1:]]

        cursor_start = line_start + len(prefix)

        # meta = [{"start": cursor_start, "end": cursor_pos, "text": sug, "type": "typ"} for sug in suggestions]

        return {
            'status':       'ok',
            'matches':      suggestions,
            'cursor_start': cursor_start,
            'cursor_end':   cursor_pos,
            'metadata':     {} # {"_jupyter_types_experimental": meta}
        }