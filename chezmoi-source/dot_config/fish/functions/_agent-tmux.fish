function _agent-tmux --description "Launch a CLI agent in a tmux session"
    set -l agent $argv[1]
    set -l rest $argv[2..]

    #__ensure_secrets

    # Already inside tmux — just run the real binary
    if set -q TMUX
        command $agent $rest
        return
    end

    set -l cwd (pwd)
    set -l real_agent (command -v $agent)
    set -l session_name "$agent-"(random)
    set -l tmpdir (mktemp -d /tmp/$agent-XXXXXX)
    set -l launcher $tmpdir/run.fish
    set -l config $tmpdir/session.yaml

    # Write a launcher script so argv is passed safely without YAML quoting headaches
    echo '#!/usr/bin/env fish' > $launcher
    echo "cd "(string escape -- $cwd) >> $launcher
    set -l cmd_parts
    for arg in $rest
        set -a cmd_parts (string escape -- $arg)
    end
    echo "exec $real_agent $cmd_parts" >> $launcher
    chmod +x $launcher

    # Single-quote the cwd for YAML; escape embedded single quotes by doubling them
    set -l yaml_cwd (string replace -a "'" "''" -- $cwd)

    # Write the tmuxp session config
    begin
        echo "session_name: $session_name"
        echo "start_directory: '$yaml_cwd'"
        echo "windows:"
        echo "  - window_name: $agent"
        echo "    layout: main-horizontal"
        echo "    panes:"
        echo "      - shell_command: $launcher"
        echo "        focus: true"
        echo "      - "
    end > $config

    tmuxp load $config
    rm -rf $tmpdir
end
