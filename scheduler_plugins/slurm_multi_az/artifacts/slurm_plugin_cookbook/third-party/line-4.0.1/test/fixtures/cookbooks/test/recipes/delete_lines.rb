directory '/tmp'

template '/tmp/samplefile1'

template '/tmp/samplefile2'

# just dup the files for regexp tests

file '/tmp/samplefile1-regexp' do
  content lazy { IO.binread('/tmp/samplefile1') }
end

file '/tmp/samplefile2-regexp' do
  content lazy { IO.binread('/tmp/samplefile2') }
end

# string tests

delete_lines 'Operation 5' do
  path '/tmp/samplefile1'
  pattern '^HI.*'
  backup true
end

delete_lines 'Operation 6' do
  path '/tmp/samplefile1'
  pattern '^#.*'
end

delete_lines 'Operation 7' do
  path '/tmp/samplefile1'
  pattern '^#.*'
end

delete_lines 'Operation 8' do
  path '/tmp/samplefile2'
  pattern '^#.*'
end

# regexp tests

delete_lines 'Operation 5 regexp' do
  path '/tmp/samplefile1-regexp'
  pattern /^HI.*/
end

delete_lines 'Operation 6 regexp' do
  path '/tmp/samplefile1-regexp'
  pattern /^#.*/
end

delete_lines 'Operation 7 regexp' do
  path '/tmp/samplefile1-regexp'
  pattern /^#.*/
end

delete_lines 'Operation 8 regexp' do
  path '/tmp/samplefile2-regexp'
  pattern /^#.*/
end

file '/tmp/emptyfile' do
  content ''
end

delete_lines 'Empty file should not change' do
  path '/tmp/emptyfile'
  pattern /line/
end

file 'prep for test /tmp/nofilehere' do
  path '/tmp/nofilehere'
  action :delete
end

delete_lines 'missing_file fail' do
  path '/tmp/nofilehere'
  pattern '^#.*'
  ignore_missing false
  ignore_failure true
end

delete_lines 'missing_file' do
  path '/tmp/nofilehere'
  pattern '^#.*'
end
