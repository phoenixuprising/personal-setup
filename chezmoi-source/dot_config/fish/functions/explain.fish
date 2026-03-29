function explain
    if test (count $argv) -eq 0
        echo "Usage: explain <function-name>"
        return 1
    end

    set -l func_name $argv[1]
    set -l md_file $HOME/.config/fish/functions/$func_name.md

    if not test -f $md_file
        echo "No documentation found for '$func_name'"
        echo "Expected: $md_file"
        return 1
    end

    if command -q glow
        glow $md_file
    else if command -q bat
        bat --language=markdown --style=plain $md_file
    else
        cat $md_file
    end
end
