"""rdktr rules compiler package.

Modules:
    constants   binary format and pattern-language limits
    normalize   text normalization (mirrors src/normalize.c)
    rule_file   rule file parsing: front matter + pattern line tokenization
    trie        double-array trie for words and prefix stems
    compiler    pattern lines -> element sequences (the Compiler class)
    serialize   compiled ruleset -> binary blob and C-file
"""
