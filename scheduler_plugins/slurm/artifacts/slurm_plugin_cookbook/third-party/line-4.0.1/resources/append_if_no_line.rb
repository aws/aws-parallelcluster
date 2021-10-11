property :backup, [true, false, Integer], default: false
property :eol, String
property :ignore_missing, [true, false], default: true
property :line, String
property :path, String

resource_name :append_if_no_line
provides :append_if_no_line
unified_mode true

action :edit do
  raise_not_found
  sensitive_default
  eol = default_eol
  backup_if_true
  add_line = chomp_eol(new_resource.line)
  string = Regexp.escape(add_line)
  regex = /^#{string}$/
  current = target_current_lines

  file new_resource.path do
    content((current + [add_line + eol]).join(eol))
    backup new_resource.backup
    sensitive new_resource.sensitive
    not_if { ::File.exist?(new_resource.path) && !current.grep(regex).empty? }
  end
end

action_class do
  include Line::Helper
end
