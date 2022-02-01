property :backup, [true, false, Integer], default: false
property :eol, String
property :ignore_missing, [true, false], default: true
property :line, String
property :path, String
property :pattern, [String, Regexp]
property :replace_only, [true, false], default: false
property :remove_duplicates, [true, false], default: false

resource_name :replace_or_add
provides :replace_or_add
unified_mode true

action :edit do
  raise_not_found
  sensitive_default
  eol = default_eol
  backup_if_true
  add_line = chomp_eol(new_resource.line)
  found = false
  regex = new_resource.pattern.is_a?(String) ? /#{new_resource.pattern}/ : new_resource.pattern
  new = []
  current = target_current_lines

  # replace
  current.each do |line|
    if line =~ regex || line == add_line
      next if found && new_resource.remove_duplicates
      line = add_line
      found = true
    end
    new << line.dup
  end

  # add
  new << add_line unless found || new_resource.replace_only

  # Last line terminator
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
end
