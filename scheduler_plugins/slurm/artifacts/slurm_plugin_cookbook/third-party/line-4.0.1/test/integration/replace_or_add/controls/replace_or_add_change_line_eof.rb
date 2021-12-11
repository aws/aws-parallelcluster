control 'Change the last line of a file' do
  eol = os.family == 'windows' ? "\r\n" : "\n"
  describe file('/tmp/change_line_eof') do
    its('content') { should match(/^Last line changed#{eol}/) }
  end

  describe file_ext('/tmp/change_line_eof') do
    its('size_lines') { should eq 7 }
  end

  describe matches('/tmp/change_line_eof', /^Last line changed#{eol}/) do
    its('count') { should eq 1 }
  end

  # redo of resource did nothing
  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/change_line_eof redo.*n#{eol}/) }
  end
end
