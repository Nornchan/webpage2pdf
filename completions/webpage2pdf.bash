# bash completion for webpage2pdf / w2p
_webpage2pdf() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    opts="-h --help -V --version -o --output -d --dir --from-list --style
          --preset --links --toc --no-toc --no-numbering --no-images --no-url
          --no-standfirst --keep-html --timeout --list-styles --list-presets
          --open --doctor -q --quiet -p --profile -f --format --list-profiles
          -j --jobs --no-cache --refresh --cache-info --clear-cache --fix"

    case "${prev}" in
        --links)
            COMPREPLY=( $(compgen -W "plain endnotes footnotes keep" -- "${cur}") )
            return 0 ;;
        -p|--profile)
            COMPREPLY=( $(compgen -W "$(webpage2pdf --list-profiles 2>/dev/null | cut -d" " -f1)" -- "${cur}") )
            return 0 ;;
        -f|--format)
            COMPREPLY=( $(compgen -W "pdf html epub md" -- "${cur}") )
            return 0 ;;
        --preset)
            COMPREPLY=( $(compgen -W "$(webpage2pdf --list-presets 2>/dev/null | cut -d" " -f1)" -- "${cur}") )
            return 0 ;;
        --style)
            # Ask the tool itself, so new stylesheets complete without edits here.
            COMPREPLY=( $(compgen -W "$(webpage2pdf --list-styles 2>/dev/null)" -- "${cur}") )
            return 0 ;;
        -d|--dir)
            COMPREPLY=( $(compgen -d -- "${cur}") )
            return 0 ;;
        -o|--output|--keep-html|--from-list)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0 ;;
        --timeout)
            return 0 ;;
    esac

    if [[ ${cur} == -* ]]; then
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
    else
        COMPREPLY=( $(compgen -f -X '!*.@(html|htm|txt)' -- "${cur}") $(compgen -d -- "${cur}") )
    fi
}
complete -F _webpage2pdf webpage2pdf
complete -F _webpage2pdf w2p
