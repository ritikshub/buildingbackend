# The Text Toolkit

> A 20,000-line access log and one question: who is hammering the login endpoint and failing? `grep 'POST /login' | awk '$9 == 401 {print $1}' | sort | uniq -c | sort -rn | head` answers it in a few milliseconds, names one IP with **202** failed logins, and never holds more than one line in memory until the `sort`. This lesson builds each of those tools as a streaming filter in Python, then runs the real ones on the same log and gets the same numbers, including `grep` finding a 5xx count of **354** where `awk` finds **350**, and the reason the difference is a bug.

## The Problem

At 3 a.m. the dashboard says the error rate went up. The dashboard does not say why. What you have is a log file, or a stream from `tail -f`, or `journalctl`, and a set of questions: which endpoint, since when, from whom, how slow, and is it the same request id that the customer quoted in the ticket. The answers are in there. Two gigabytes of there.

You could load it into Python and write a script. By the time it runs you have lost ten minutes, and the log has rotated. The Unix answer is older and faster: seven small programs that each do one thing to a stream of lines, wired together with the pipes from lesson 07. `grep` selects lines, `awk` splits them into fields and computes, `cut` slices, `sort` orders, `uniq -c` counts, `sed` rewrites, `tr` maps characters, and `jq` does the same for JSON. None of them holds the file in memory except `sort`, so the size of the log is nearly irrelevant, and a question is one line long. This lesson teaches the seven, the regular-expression language four of them share, and the one idiom (`sort | uniq -c | sort -rn`) that answers half of all on-call questions.

## The Concept

### Every tool is a filter

A **filter** reads lines from descriptor 0, does something to each, and writes lines to descriptor 1. It knows nothing about files bigger than one line and it starts producing output before the input has finished arriving. That is why `tail -f app.log | grep ERROR` shows errors live, and why `grep ERROR 50gb.log | head -1` returns instantly (lesson 07's `SIGPIPE`). The lesson 05 read loop is underneath; the tool is what happens to each line.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 470" width="100%" style="max-width:880px" role="img" aria-label="A pipeline of six stages processing the access log, drawn left to right, with what each stage holds in memory written beneath it. The log file, 20,000 lines, feeds grep, which keeps one line at a time and passes only lines matching POST slash login. awk keeps one line plus its split fields and prints field one, the IP, when field nine equals 401. sort must hold every line it receives, here 202 of them, because it cannot emit the first line until it has seen the last; it is the only stage that does not stream. uniq minus c keeps two lines, the current and the previous, and emits a count for each run of equal lines. sort minus rn holds the counted rows, a few dozen, and orders them by number descending. head keeps a counter and closes after ten lines, which sends SIGPIPE back up the chain. Total memory across the pipeline is a few kilobytes plus the sort's 202 lines; the input size could be 20 gigabytes.">
  <defs>
    <marker id="p1l08a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Six filters, one line at a time: what each stage does and what it holds</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="60" width="90" height="70" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="75" y="88" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor">access.log</text>
    <text x="75" y="104" text-anchor="middle" font-size="8" fill="currentColor">20,000 lines</text>
    <text x="75" y="118" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">or 20 GB</text>
    <g stroke-linejoin="round" stroke-width="1.7">
      <rect x="150" y="50" width="120" height="90" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="300" y="50" width="120" height="90" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="450" y="50" width="120" height="90" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="600" y="50" width="120" height="90" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="750" y="50" width="120" height="90" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="210" y="72" font-size="9.5" font-weight="700" fill="#0fa07f">grep 'POST /login'</text>
      <text x="210" y="90" font-size="8">a regex test per line</text>
      <text x="210" y="104" font-size="8">out: the lines that match</text>
      <text x="210" y="124" font-size="8" opacity="0.7">holds: one line</text>
      <text x="360" y="72" font-size="9.5" font-weight="700" fill="#0fa07f">awk '$9==401 {print $1}'</text>
      <text x="360" y="90" font-size="8">split into fields, test, print</text>
      <text x="360" y="104" font-size="8">out: an IP per failed login</text>
      <text x="360" y="124" font-size="8" opacity="0.7">holds: one line + its fields</text>
      <text x="510" y="72" font-size="9.5" font-weight="700" fill="#d64545">sort</text>
      <text x="510" y="90" font-size="8">equal lines become adjacent</text>
      <text x="510" y="104" font-size="8">out: nothing until EOF</text>
      <text x="510" y="124" font-size="8" opacity="0.7">holds: EVERYTHING (202 lines)</text>
      <text x="660" y="72" font-size="9.5" font-weight="700" fill="#0fa07f">uniq -c</text>
      <text x="660" y="90" font-size="8">count each run of equal lines</text>
      <text x="660" y="104" font-size="8">out: "202 203.0.113.9"</text>
      <text x="660" y="124" font-size="8" opacity="0.7">holds: two lines</text>
      <text x="810" y="72" font-size="9.5" font-weight="700" fill="#e0930f">sort -rn | head</text>
      <text x="810" y="90" font-size="8">rank by count, keep 10</text>
      <text x="810" y="104" font-size="8">head closes: SIGPIPE upstream</text>
      <text x="810" y="124" font-size="8" opacity="0.7">holds: the counted rows</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M122 95 L146 95" marker-end="url(#p1l08a-ar)"/>
      <path d="M272 95 L296 95" marker-end="url(#p1l08a-ar)"/>
      <path d="M422 95 L446 95" marker-end="url(#p1l08a-ar)"/>
      <path d="M572 95 L596 95" marker-end="url(#p1l08a-ar)"/>
      <path d="M722 95 L746 95" marker-end="url(#p1l08a-ar)"/>
    </g>
    <!-- sample data flowing -->
    <rect x="30" y="166" width="840" height="150" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="450" y="188" text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">THE SAME DATA AT EACH STAGE</text>
    <g font-size="8.5" fill="currentColor">
      <text x="46" y="210">in:     203.0.113.9 - - [05/Sep/2026:03:00:07 +0000] "POST /login HTTP/1.1" 401 1204 "-" "curl/8.5.0" 31ms   (and 19,999 more)</text>
      <text x="46" y="228">grep:   the 2,294 lines containing POST /login</text>
      <text x="46" y="246">awk:    203.0.113.9  203.0.113.9  203.0.113.9 ...   (one IP per line whose field 9 is 401: 202 lines)</text>
      <text x="46" y="264">sort:   the same 202 lines, but every equal IP is now next to its twins</text>
      <text x="46" y="282">uniq -c:    202 203.0.113.9        (one row per distinct IP, with its count)</text>
      <text x="46" y="300">sort -rn | head:   the biggest counts first, ten rows: the answer</text>
    </g>
    <rect x="30" y="334" width="840" height="86" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="450" y="356" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">WHY IT SCALES</text>
    <g text-anchor="middle" font-size="8.5" fill="currentColor">
      <text x="450" y="376">every stage but sort forgets each line as soon as it has handled it, so the input can be larger than RAM and can be arriving live (tail -f)</text>
      <text x="450" y="392">shrink the stream BEFORE the sort: grep and awk first, so sort holds 202 lines and not 20,000,000</text>
      <text x="450" y="408" opacity="0.8">on the sandbox: grep over 22 MB in 39 ms; the whole count pipeline over 22 MB in 120 ms</text>
    </g>
  </g>
  <text x="450" y="450" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Select, then shape, then count, then rank. Put the stage that shrinks the stream as early as you can.</text>
</svg>
```

One rule follows from the diagram and it is the only performance rule you need: **shrink the stream before the stage that cannot stream.** `grep` and `awk` first, `sort` last, and `sort` never sees more than the lines you actually care about.

### grep: select lines with a regular expression

`grep pattern file` prints every line in which the pattern matches. The pattern is a **regular expression**, a small language for describing text, and four of the seven tools speak it (`grep`, `sed`, `awk`, and `less`'s search). The parts you will actually use:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" role="img" aria-label="A regular expression annotated piece by piece against a log line. The pattern is caret, one or more of digits or dots, a space, dot star, a quote, a group of GET or POST, a space, a group of one or more non-space characters, a space, non-quote characters star, quote, space, a group of 5 followed by two digits, space. Each piece is labelled: caret anchors at the start of the line; the bracket class with plus means one or more IP characters; dot star means anything, as little or as much as needed; the parenthesised alternation captures the method as group 1; the negated bracket class captures the path as group 2 and stops at the first space; 5 with a brace-two-digit quantifier captures a 5xx status as group 3; the surrounding spaces stop it from matching a 500-byte response size. A table below lists the atoms: dot any character, brackets a class, negated brackets, star zero or more, plus one or more, question mark optional, braces exact counts, pipe alternation, parentheses grouping and capture, caret and dollar anchors, backslash to make a special character literal, and the note that basic grep needs backslashes before plus, question mark, braces, pipe and parentheses while grep -E, sed -E and awk do not, and grep -F treats the pattern as literal text.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One regular expression, taken apart against the line it matches</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="30" y="48" width="840" height="40" rx="8" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.4"/>
    <text x="450" y="73" text-anchor="middle" font-size="10.5" fill="currentColor">10.0.2.17 - - [05/Sep/2026:03:12:44 +0000] "GET /api/orders HTTP/1.1" 500 1834 "-" "curl/8.5.0" 1207ms</text>
    <rect x="30" y="102" width="840" height="40" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="450" y="127" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">^[0-9.]+ .* "(GET|POST) ([^ ]+) [^"]*" (5[0-9]{2}) </text>
    <!-- annotations -->
    <g font-size="8.5" fill="currentColor">
      <text x="46" y="168" font-weight="700" fill="#0fa07f">^</text><text x="70" y="168">start of the line: nothing may come before</text>
      <text x="46" y="186" font-weight="700" fill="#0fa07f">[0-9.]+</text><text x="120" y="186">one or more digits or dots: the IP. A class in brackets; + means "at least one"</text>
      <text x="46" y="204" font-weight="700" fill="#0fa07f">.*</text><text x="70" y="204">anything, any length: skips the dashes and the timestamp. Greedy, but it backs up if the rest cannot match</text>
      <text x="46" y="222" font-weight="700" fill="#0fa07f">"(GET|POST) </text><text x="150" y="222">a literal quote, then GET or POST captured as group 1, then a space</text>
      <text x="46" y="240" font-weight="700" fill="#0fa07f">([^ ]+)</text><text x="120" y="240">one or more NON-space characters: the path, group 2. [^ ] means "not a space"; it stops at the first one</text>
      <text x="46" y="258" font-weight="700" fill="#0fa07f">[^"]*"</text><text x="120" y="258">the rest of the quoted request up to the closing quote</text>
      <text x="46" y="276" font-weight="700" fill="#0fa07f"> (5[0-9]{2}) </text><text x="150" y="276">space, a 5 and exactly two digits, space: a 5xx status, group 3. The spaces are why 1834 bytes or 500ms cannot match</text>
    </g>
    <rect x="30" y="296" width="840" height="110" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-width="1.5" stroke-linejoin="round"/>
    <text x="450" y="316" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">THE ATOMS YOU NEED</text>
    <g font-size="8.5" fill="currentColor">
      <text x="46" y="336">.  any one character      [abc] [0-9] [[:digit:]]  a class      [^x]  not x      *  zero or more      +  one or more      ?  optional</text>
      <text x="46" y="354">{3} {2,5}  exact counts      a|b  either      ( )  group and capture (\1 in sed)      ^ $  start and end of line      \.  a literal dot</text>
      <text x="46" y="374">grep and sed use "basic" syntax where + ? { } | ( ) need a backslash to be special; grep -E, sed -E and awk use "extended" syntax where they just are.</text>
      <text x="46" y="392">grep -F takes the pattern as literal text (fast, and safe for IPs, paths and anything with dots). When in doubt, -E for patterns and -F for strings.</text>
    </g>
  </g>
  <text x="450" y="424" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">Anchor it, bound it with the characters around it, and test it on three lines before you trust it on a million.</text>
</svg>
```

The flags worth having in your fingers: `-c` count matches, `-v` invert, `-i` ignore case, `-n` line numbers, `-o` print only the matched part, `-E` extended syntax, `-F` literal, `-r` recurse through a directory, `-l` list files that match, `-m1` stop at the first match, `-B3 -A3` three lines of context before and after, and `--line-buffered` for use on `tail -f` (lesson 07's buffering). And one trap the sandbox shows in the numbers: **a pattern without boundaries matches more than you meant.** `grep -c ' 50[0-9] '` reports 354 lines; `awk '$9 >= 500'` reports 350. The four extra are responses whose *size* was between 500 and 509 bytes, which also sits between two spaces. Anchor the status by its position or use `awk` when you mean a field.

### awk: fields, then a program per line

`awk` is what you reach for when a line has columns. It splits each line on whitespace (or on the separator given with `-F`) into `$1`, `$2`, ... `$NF` (`NF` is the number of fields, so `$NF` is the last one), then runs a program written as `pattern { action }` pairs: the action runs for every line where the pattern is true. Either half is optional: a pattern alone prints matching lines; an action alone runs on every line. `NR` is the line number, `BEGIN` and `END` blocks run once before and after, and variables are created by using them:

```console
$ awk '{print $1}' access.log | head -3                # field 1: the IP
10.0.0.141
10.0.1.157
10.0.1.27
$ awk '$9 >= 500' access.log | wc -l                   # a pattern alone: print lines where field 9 is 5xx
350
$ awk '{s += $NF} END {print s / NR, "ms"}' access.log # sum the last field, divide by the line count
51.9925 ms
$ awk '$NF+0 > 1000 {print $7, $NF}' access.log | head -3
/static/app.js 1022ms
/login 1006ms
/api/users/me 1051ms
```

Two things to notice. `awk` reads `1207ms` as the number 1207 when you do arithmetic on it, and `$NF+0` forces that (otherwise `"900ms" > 1000` would be a string comparison). And it has associative arrays, which turn it into a one-line group-by:

```console
$ awk '{n[$7]++; s[$7] += $NF} END {for (p in n) printf "%8.1f ms %6d  %s\n", s[p]/n[p], n[p], p}' access.log | sort -rn | head -4
    59.2 ms   2155  /health
    57.7 ms   2178  /
    55.3 ms   2248  /static/app.js
    53.7 ms   2159  /checkout
```

Average latency and request count per endpoint, from a raw log, in one line. That is the point at which most engineers stop writing Python for log questions. `-F'"'` splits on the double quote, which is the easy way to get at a quoted field like the user agent: `awk -F'"' '{print $6}'`.

### cut and tr: the simple slicers

`cut` takes fields by a single-character delimiter (`-d' ' -f1,9`) or characters by position (`-c1-15`). It is faster than `awk` and dumber: it splits on exactly one character, so two spaces make an empty field, and it cannot compute. Use it when the columns are regular (CSV, `/etc/passwd`, `ps` output), and `awk` when they are not.

`tr` maps characters to characters: `tr 'a-z' 'A-Z'` upper-cases, `tr -d '"'` deletes a character, `tr -s ' '` squeezes runs of spaces into one, `tr ':' '\n'` turns `$PATH` into lines (lesson 03 used it). It is not a regex tool; it is a byte table, and that is why it is fast.

### sed: rewrite lines

`sed` is the stream editor: for every line, apply a command, print the result. Ninety per cent of its use is one command, substitute:

```console
$ sed 's/10\.0\./INTERNAL./' access.log | head -1 | cut -c1-40         # first match on each line
INTERNAL.0.141 - - [05/Sep/2026:03:00:00
$ sed -E 's#"(GET|POST) ([^ ]+) [^"]*"#\1 \2#' access.log | head -1     # groups, and # as the delimiter
10.0.0.141 - - [05/Sep/2026:03:00:00 +0000] POST /checkout 200 28334 "-" ...
$ sed -n '5,7p' access.log                                                # -n: print nothing unless told; 5,7p: lines 5 to 7
$ sed '/health/d' access.log | wc -l                                      # delete lines matching
17845
$ sed -i 's/curl/CURL/g' copy.log                                         # in place; g: every match on the line
```

Any character can be the delimiter, which is why `#` appears when the pattern has slashes in it. `\1` and `\2` are the captured groups. `-E` gives extended regex syntax. `-i` edits the file in place (GNU `sed` writes a temp file and renames it, lesson 05's atomic replace), and `-i.bak` keeps a backup. For anything more than substitute, delete and print ranges, `awk` or a real script is clearer.

### The counting idiom: sort | uniq -c | sort -rn

`uniq -c` collapses **adjacent** equal lines into one line with a count. It only works if equal lines are next to each other, which is what `sort` is for. Then `sort -rn` orders the counts, largest first, and `head` keeps the top. That is the whole idiom, and it answers "top N of anything":

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 380" width="100%" style="max-width:880px" role="img" aria-label="The counting idiom shown with real data. Stage one, awk prints field 9, the status, producing a stream like 200 200 403 200 500 200 404 in file order. Stage two, sort, groups equal values so the stream becomes 200 200 200 200 301 403 404 500 in order. Stage three, uniq -c, collapses each run into a count and the value: 16378 200, 355 301, 2029 403, 686 404, 257 500, 202 401, 93 502. Stage four, sort -rn, orders those rows numerically by the count, descending: 16378 200, 2029 403, 686 404, 355 301, 257 500, 202 401, 93 502. A note says uniq needs adjacency which sort provides, that sort -n compares numbers rather than text so 93 does not sort above 686, and that the first sort is the only stage that reads its whole input, so filter first.">
  <defs>
    <marker id="p1l08c-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">sort | uniq -c | sort -rn: extract a key, group it, count the groups, rank the counts</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g stroke-linejoin="round" stroke-width="1.7">
      <rect x="30"  y="56" width="195" height="230" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="245" y="56" width="195" height="230" rx="9" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="460" y="56" width="195" height="230" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="675" y="56" width="195" height="230" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700">
      <text x="127" y="78" fill="#0fa07f">awk '{print $9}'</text>
      <text x="342" y="78" fill="#d64545">sort</text>
      <text x="557" y="78" fill="#0fa07f">uniq -c</text>
      <text x="772" y="78" fill="#e0930f">sort -rn</text>
    </g>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">
      <text x="127" y="92">extract the key</text>
      <text x="342" y="92">make equal keys adjacent</text>
      <text x="557" y="92">collapse runs into counts</text>
      <text x="772" y="92">order by the number</text>
    </g>
    <g font-size="9" fill="currentColor">
      <text x="60" y="118">200</text><text x="60" y="134">200</text><text x="60" y="150">403</text><text x="60" y="166">200</text><text x="60" y="182">500</text><text x="60" y="198">200</text><text x="60" y="214">404</text><text x="60" y="230">200</text><text x="60" y="246">...</text>
      <text x="275" y="118">200</text><text x="275" y="134">200</text><text x="275" y="150">200</text><text x="275" y="166">200</text><text x="275" y="182">301</text><text x="275" y="198">403</text><text x="275" y="214">404</text><text x="275" y="230">500</text><text x="275" y="246">...</text>
      <text x="490" y="118">16378 200</text><text x="490" y="134">  355 301</text><text x="490" y="150">  202 401</text><text x="490" y="166"> 2029 403</text><text x="490" y="182">  686 404</text><text x="490" y="198">  257 500</text><text x="490" y="214">   93 502</text>
      <text x="705" y="118">16378 200</text><text x="705" y="134"> 2029 403</text><text x="705" y="150">  686 404</text><text x="705" y="166">  355 301</text><text x="705" y="182">  257 500</text><text x="705" y="198">  202 401</text><text x="705" y="214">   93 502</text>
    </g>
    <g text-anchor="middle" font-size="7.8" fill="currentColor" opacity="0.7">
      <text x="127" y="270">file order; one line per request</text>
      <text x="342" y="270">holds all 20,000; emits at EOF</text>
      <text x="557" y="270">compares each line to the previous</text>
      <text x="772" y="270">-n: numbers, so 93 sorts below 686</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M227 170 L241 170" marker-end="url(#p1l08c-ar)"/>
      <path d="M442 170 L456 170" marker-end="url(#p1l08c-ar)"/>
      <path d="M657 170 L671 170" marker-end="url(#p1l08c-ar)"/>
    </g>
    <rect x="30" y="304" width="840" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.4" stroke-linejoin="round"/>
    <text x="450" y="324" text-anchor="middle" font-size="8.5" fill="currentColor">Change the awk and the same four stages count anything: IPs ($1), paths ($7), user agents (-F'"' $6), minutes (substr($4,2,17)), error messages.</text>
    <text x="450" y="340" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">When the input is already grouped (timestamps in a log written in order), skip the first sort: uniq -c alone is enough.</text>
  </g>
  <text x="450" y="372" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Half of all on-call questions are "top N of X." This is the answer, with X supplied by awk.</text>
</svg>
```

`sort`'s flags do most of the shaping: `-n` numeric, `-r` reverse, `-k12` sort by field 12, `-t,` set the field separator, `-u` unique, `-h` human sizes (`1.5G` above `200M`). `uniq -d` shows only the duplicated lines, `uniq -u` only the singletons. And `sort` on a huge input spills to temporary files under `/tmp`, which is one more reason to `grep` first.

### jq: the same questions when the log is JSON

More and more services write **JSON lines**: one object per line, with named fields. Field numbers stop mattering and `jq` takes over. Its language is a path: `.status` reads a key, `.req.path` walks two, `.[0]` indexes an array, `select(.status >= 500)` keeps matching objects, `-r` prints strings without quotes, `-c` prints compact objects, `@tsv` turns an array into tab-separated columns for `awk`, and `-s` slurps the whole file into one array (the non-streaming mode, for averages):

```console
$ jq -r 'select(.status >= 500) | .req.path' access.log.jsonl | sort | uniq -c | sort -rn | head -3
     53 /health
     51 /
     49 /static/app.js
$ jq -r '[.ts, .status, .req.path] | @tsv' access.log.jsonl | head -2
05/Sep/2026:03:00:00 +0000	200	/checkout
05/Sep/2026:03:00:00 +0000	200	/static/app.js
$ jq -s 'map(.ms) | add / length' access.log.jsonl
51.9925
```

Same answers as `awk` gave on the text log, because the data is the same. The difference shows up the day someone adds a column: `$9` silently becomes the wrong field, `.status` does not. That is the argument for JSON logs, and Phase 10 makes it at length.

## Build It

The script for this lesson is [`code/textkit.py`](../code/textkit.py). It generates a realistic 20,000-line access log (and the same data as JSON lines), then implements each tool as a generator over lines and asks the questions an on-call engineer asks. Every function is a filter: it takes an iterator of lines and yields lines, so the file is never in memory and the functions chain exactly like the commands they mirror. Pass `--keep` to leave the log where the real tools can reach it:

```bash
python3 phases/01-linux-and-the-command-line/08-the-text-toolkit/code/textkit.py
make shell
python3 phases/01-linux-and-the-command-line/08-the-text-toolkit/code/textkit.py --keep   # then cd /tmp/textkit-* and use the real tools
```

**`grep`** is a compiled regex tested per line; `-v`, `-c`, `-o` are one flag each:

```python
def grep(pattern, src, invert=False, ignore_case=False, count=False, only=False):
    rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    n = 0
    for line in src:
        m = rx.search(line)
        if bool(m) != invert:
            n += 1
            if not count:
                yield m.group(0) if (only and m) else line
    if count:
        yield str(n)
```

**`awk`** is a split and a callback per line; the callback is the `pattern { action }` program:

```python
def awk(src, program, sep=None):
    for line in src:
        fields = line.split(sep) if sep else line.split()
        out = program(fields, line)          # returns a string to print, or None
        if out is not None:
            yield out
```

**`sort | uniq -c | sort -rn`** is the one place a whole stream is held, and a `Counter` is the honest way to say so:

```python
def sort_uniq_c(src, reverse=True, top=None):
    counts = collections.Counter(src)        # sort cannot stream: it must see every line
    rows = counts.most_common(top) if reverse else sorted(counts.items())
    for value, n in rows:
        yield f"{n:7d} {value}"
```

Chain them and the on-call question is three nested calls, printing the same row the real pipeline prints:

```console
5 · The on-call question: who is hammering /login and failing?
   grep 'POST /login' | grep ' 401 ' | awk '{print $1}' | sort | uniq -c | sort -rn | head -3
       202 203.0.113.9
   one IP, hundreds of failed logins: that is a credential-stuffing attempt (Phase 8, lesson 12), found in one pipeline
```

The rest of the transcript is the vocabulary applied: 350 lines with a 5xx status, 3,622 non-200 lines, an average latency of 52.0 ms, 22 requests over one second, the top five IPs, the status histogram, which paths produce the 5xx (`/health` leads with 53), 167 requests per minute from the timestamps, `sed` and `tr` rewriting a line, and the `jq` walk over the JSON version giving the same three paths. Read each block against the function that produced it; none is more than fifteen lines.

## Use It

The real tools on the log the script kept, inside `make shell`. Every number below matches the script's, except the one that is a lesson:

```console
$ grep -c ' 50[0-9] ' access.log;  awk '$9 >= 500' access.log | wc -l
354
350                       <- grep also matched four lines whose byte count was 50x; awk tested the field
$ grep -o 'GET [^ ]*' access.log | head -2
GET /static/app.js
GET /api/orders/42
$ grep -E '(500|502) [0-9]+ "-" "curl' access.log | wc -l;  grep -F '203.0.113.9 ' access.log | wc -l
78
1753
$ grep -B1 -A1 -m1 ' 502 ' access.log | cut -c1-50     # one line of context each side of the first 502
10.0.2.135 - - [05/Sep/2026:03:01:52 +0000] "POST
10.0.1.157 - - [05/Sep/2026:03:01:52 +0000] "GET /
10.0.3.18 - - [05/Sep/2026:03:01:53 +0000] "GET /h
```

Basic versus extended syntax, and literal matching, on toy input:

```console
$ echo aaa123 | grep 'a\{3\}';  echo aaa123 | grep -E 'a{3}[0-9]+';  echo aaa123 | grep -E '^a+[0-9]{3}$'
aaa123
aaa123
aaa123
$ echo xzy | grep 'x.y';  echo xzy | grep -F 'x.y' || echo '(no match: -F is literal)'
xzy
(no match: -F is literal)
```

`awk` computing, `cut` slicing, `sed` rewriting:

```console
$ awk -F'"' '{print $6}' access.log | sort | uniq -c | sort -rn      # user agents: split on the quote
   5158 curl/8.5.0
   4981 Go-http-client/2.0
   4945 Mozilla/5.0 (X11; Linux x86_64)
   4916 python-requests/2.32
$ cut -d' ' -f1,9 access.log | head -2;  echo 'a   b    c' | tr -s ' '
10.0.0.141 200
10.0.1.157 200
a b c
$ sed -n '5,7p' access.log | cut -c1-40;  sed '/health/d' access.log | wc -l;  sed -i 's/curl/CURL/g' copy.log;  grep -c CURL copy.log
10.0.3.235 - - [05/Sep/2026:03:00:01 +00
10.0.1.24 - - [05/Sep/2026:03:00:01 +000
10.0.1.27 - - [05/Sep/2026:03:00:02 +000
17845
5158
```

The counting idiom answering four questions, percentiles from a sort, and `uniq -d`:

```console
$ awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -3
   1753 203.0.113.9
    623 10.0.3.18
    603 10.0.1.102
$ awk '{print $1}' access.log | sort -u | wc -l
59
$ awk '{print $NF+0}' access.log | sort -n | awk '{a[NR]=$1} END {print "p50", a[int(NR*0.5)], "p95", a[int(NR*0.95)], "p99", a[int(NR*0.99)]}'
p50 25 p95 127 p99 919
$ grep 'POST /login' access.log | awk '$9 == 401 {print $1}' | sort | uniq -c | sort -rn | head -2
    202 203.0.113.9
$ awk '$9 >= 500 {print substr($4, 2, 17)}' access.log | uniq -c | sort -rn | head -3     # when did the errors cluster?
      9 05/Sep/2026:03:58
      7 05/Sep/2026:04:39
      7 05/Sep/2026:03:23
$ printf 'b\na\nb\nc\nb\n' | sort | uniq -d;  printf '1.5G\n200M\n3K\n' | sort -h
b
3K
200M
1.5G
```

And the reason to learn these rather than reaching for Python: speed, on the same question, and streaming on a file ten times the size:

```console
$ time grep -c ' 500 ' access.log
257
real    0m0.004s
$ time python3 -c 'print(sum(1 for l in open("access.log") if " 500 " in l))'
257
real    0m0.019s
$ for i in $(seq 10); do cat access.log; done > big.log;  ls -lh big.log | awk '{print $5}'
22M
$ time grep -c ' 502 ' big.log
930
real    0m0.039s
$ time (awk '{print $9}' big.log | sort | uniq -c | sort -rn | head -1)
 163780 200
real    0m0.120s
```

Five times faster than a Python one-liner on 2 MB, and the whole count pipeline over 22 MB in 120 ms. On a real log at 3 a.m., that is the difference between an answer and a script you are still writing.

## Ship It

The artifact for this lesson is a runbook: [`outputs/runbook-log-triage-one-liners.md`](../outputs/runbook-log-triage-one-liners.md). It is the first ten minutes with a raw log, as one-liners: is it broken and how badly (error rate, status histogram, 5xx by endpoint, 5xx per minute, live errors from `tail -f`); who is doing it (top IPs, failures by IP, one client's whole day, failed logins, user agents); what is slow (average, slowest requests, p95, latency by endpoint); how much traffic (per minute, per second peak, bytes by endpoint, distinct clients); one request's whole story across files; rotated and compressed logs with `zgrep` and `journalctl`; and the `jq` equivalents for JSON logs. Every entry names the field it depends on and the trap beside it.

## Think about it

1. `grep -c 500 access.log` gives 1,204 and `awk '$9 == 500' | wc -l` gives 257. List three places on a log line where the digits `500` can appear other than the status, and write the `grep` that matches only the status.
2. `sort | uniq -c | sort -rn` on a 40 GB log runs out of `/tmp`. Which stage is responsible, and what two changes to the pipeline fix it without changing the answer?
3. `tail -f app.log | grep ERROR | awk '{print $3}'` shows nothing for a minute during an incident and then twenty lines at once. Which lesson 07 mechanism, in which of the two filters, and what flag fixes it?
4. A colleague argues the team should switch the service to JSON logs. Using the `$9` versus `.status` example, give one operational argument for and one against.

## Key takeaways

- The seven tools are **filters**: one line in, one line out, never the whole file. Only **`sort`** must see everything, so **shrink the stream before it**: `grep` and `awk` first.
- **`grep`** selects lines by regular expression: anchors (`^ $`), classes (`[0-9]`, `[^ ]`), quantifiers (`* + ? {n}`), groups and alternation (`(a|b)`). `-E` for extended syntax, `-F` for literal text, `-c -v -i -o -n -r -l -B -A` for the rest. **Bound the pattern**, or `500` matches a byte count.
- **`awk`** splits lines into `$1`..`$NF` and runs `pattern { action }` per line, with `NR`, `END`, arithmetic and associative arrays. Sums, averages, per-key counts and field comparisons are one line. `$NF+0` forces a number.
- **`cut`** slices by one delimiter or by column; **`tr`** maps characters; **`sed`** substitutes (`s/a/b/g`, `-E`, `\1`, any delimiter), deletes (`/x/d`), prints ranges (`-n '5,7p'`), and edits in place (`-i`).
- **`sort | uniq -c | sort -rn | head`** is "top N of anything." `uniq` needs adjacency; `sort -n` compares numbers; `-k` and `-t` pick a field; `-h` understands sizes; `-u` dedups.
- **`jq`** does the same for JSON lines: `.a.b`, `select()`, `-r`, `@tsv`, `-s`. Named fields survive schema changes; `$9` does not.
- `grep` is five times faster than a Python one-liner and streams 22 MB in 39 ms. Learn the idioms; write a script when the `awk` no longer fits on a line.

Next: [Shell Scripting](../09-shell-scripting-for-operations/). A one-liner that runs every day is a script. Now the six habits that make a script safe to run on a server, the same deploy script in bash and in Python side by side, and `shellcheck`.
