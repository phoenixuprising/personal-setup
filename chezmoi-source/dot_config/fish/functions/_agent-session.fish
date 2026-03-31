function _agent-session --description "Start an agent session"
    set -l agent $argv[1]
    set -l rest $argv[2..]

    # If a path argument was passed, use it as working directory
    if test (count $rest) -gt 0; and test -e "$rest[1]"
        set -x CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR true
        cd "$rest[1]"
        command $agent $rest[2..]
        return
    end

    set -x CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR true
    cd ~/system-ai
    command $agent $rest
end
