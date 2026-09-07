# fish completion for webpage2pdf / w2p

function __w2p_styles
    webpage2pdf --list-styles 2>/dev/null
end

for cmd in webpage2pdf w2p
    complete -c $cmd -s h -l help        -d "Show help and exit"
    complete -c $cmd -s V -l version     -d "Show version and exit"
    complete -c $cmd -s o -l output -r -F -d "Exact output PDF path (single source only)"
    complete -c $cmd -s d -l dir -x -a "(__fish_complete_directories)" -d "Output directory"
    complete -c $cmd -l from-list -r -F  -d "Read sources from a file, one per line"
    complete -c $cmd -l style -x -a "(__w2p_styles)" -d "Stylesheet name"
    complete -c $cmd -l links -x -a "plain\t'Strip link styling' endnotes\t'Numbered list at the end' footnotes\t'URL at the foot of its page' keep\t'Leave links live'" -d "How to treat links"
    complete -c $cmd -l no-numbering     -d "Omit section and figure numbers"
    complete -c $cmd -l no-images        -d "Text only — smaller files"
    complete -c $cmd -l no-url           -d "Omit source URL from title block"
    complete -c $cmd -l no-standfirst    -d "Omit the italic summary line"
    complete -c $cmd -l keep-html -r -F  -d "Also save the cleaned HTML"
    complete -c $cmd -l timeout -x       -d "Network timeout per request (seconds)"
    complete -c $cmd -l preset -x -a "a4 letter a5 book remarkable two-column" -d "Page geometry"
    complete -c $cmd -l toc              -d "Add a contents list with page numbers"
    complete -c $cmd -l no-toc           -d "Never add a contents list"
    complete -c $cmd -l open             -d "Open the finished PDF"
    complete -c $cmd -l list-presets     -d "Show available page presets and exit"
    complete -c $cmd -l list-styles      -d "Show available stylesheets and exit"
    complete -c $cmd -l doctor           -d "Check the installation"
    complete -c $cmd -s q -l quiet       -d "Only print errors"
end
