delete_lines 'missing_file fail' do
  path '/tmp/nofilehere'
  pattern '^#.*'
  ignore_missing false
end
