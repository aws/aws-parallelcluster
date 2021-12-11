# ============ between
control 'filter_lines - Verify the code to use filters. Verify several example filters' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/between') do
    between_match = Regexp.escape("empty_list=#{eol}add line#{eol}empty_delimited_list=()#{eol}")
    its(:content) { should match(/#{between_match}/m) }
  end
  describe file_ext('/tmp/between') do
    its('size_lines') { should eq 21 }
  end

  describe file('/tmp/comment') do
    its(:content) { should match(/# last_list/) }
  end

  describe file_ext('/tmp/comment') do
    its('size_lines') { should eq 20 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Change lines between matches redo.*n/) }
  end
end
