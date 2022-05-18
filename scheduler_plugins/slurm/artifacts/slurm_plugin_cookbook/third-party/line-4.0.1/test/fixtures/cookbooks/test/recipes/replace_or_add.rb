directory '/tmp'

template '/tmp/samplefile' do
end

template '/tmp/samplefile2' do
end

replace_or_add 'Operation 2' do
  path '/tmp/samplefile'
  pattern 'hey there.*'
  line 'hey there how you doin'
  backup true
end

replace_or_add 'Operation 3' do
  path '/tmp/samplefile'
  pattern 'hey there.*'
  line 'hey there how you doin'
end

replace_or_add 'Operation 4' do
  path '/tmp/samplefile2'
  pattern 'ssh-dsa AAAAB3NzaC1yc2EAAAADDEADBEEF.*'
  line ''
end

replace_or_add 'Operation 5' do
  path '/tmp/samplefile2'
  pattern 'ssh-rsa'
  line 'ssh-rsa change 1'
end

replace_or_add 'Operation 6' do
  path '/tmp/samplefile2'
  pattern 'ssh-rsa'
  line 'ssh-rsa change 2'
end

file '/tmp/emptyfile' do
  content ''
end

replace_or_add 'Do nothing to the empty file' do
  path '/tmp/emptyfile'
  pattern 'line'
  line 'line add'
  replace_only true
end
