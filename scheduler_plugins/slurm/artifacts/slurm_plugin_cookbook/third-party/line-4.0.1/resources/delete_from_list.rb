property :backup, [true, false, Integer], default: false
property :delim, Array
property :entry, String
property :ends_with, String
property :eol, String
property :ignore_missing, [true, false], default: true
property :path, String
property :pattern, [String, Regexp]

resource_name :delete_from_list
provides :delete_from_list
unified_mode true

action :edit do
  return if !target_file_exist? && new_resource.ignore_missing
  raise_not_found
  sensitive_default
  eol = default_eol
  backup_if_true
  current = target_current_lines
  new = delete_list_entry(current)

  new[-1] += eol unless new[-1].to_s.empty?
  file new_resource.path do
    content new.join(eol)
    backup new_resource.backup
    sensitive new_resource.sensitive
    not_if { new == current }
  end
end

action_class do
  include Line::Helper
  include Line::ListHelper
end
