# IGHCi

Nothing really interesting — just a minimalistic kernel for Haskell.

<img width="300" height="1068" alt="screenshot" align="right" src="https://github.com/user-attachments/assets/3ca15010-8ee3-44fa-b5fd-074ed49fa9a0" />

I’ve never managed to successfully build [IHaskell](https://github.com/IHaskell/IHaskell), and I strongly dislike Docker and other bloated software. Jupyter is also extremely bloated, and perhaps someday a delightful individual will provide us with an alternative based on `acme` and `9p`. Until that day, however, we have to put up with it. I also find the Haskell tooling (`cabal`/`stack`) to be rather atrocious. 

This kernel is not tied to anything except `ghci`, so you can easily use the latest versions of `ghc`. It supports `ghc` versions >= 9.10 because it uses the `-fdiagnostics-as-json` flag.

It currently uses `pexpect` to control ghci, though I hope to remove that dependency in the future.

**Supported features:**

*   **Modules:** Files are created in a temporary directory. It is important to note that the entire context of `ghci` is cleared after loading a module. However, you can load multiple modules that import each other.
*   **Simple HTML output:** Any output enclosed in `<html>…</html>` tags is treated as HTML. LaTeX via MathJax can also be used through HTML.
*   **Autocomplete**


**Installation:**

```
pip install .
IGHCi-install
```

**FAQ:**

— The “i” in GHCi stands for “interactive,” which makes IGHCi an abbreviation for “Interactive Glasgow Haskell Compiler interactive.” That doesn't make much sense, does it?

— Yes.
