function _claude-session --description "Start a Claude session with specified model"
   set -x CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR true
   cd ~/empty
   claude --model $argv[1]
end
