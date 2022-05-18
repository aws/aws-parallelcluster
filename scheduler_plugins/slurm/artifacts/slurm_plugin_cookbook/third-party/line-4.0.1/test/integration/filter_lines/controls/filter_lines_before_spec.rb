# ============ before
control 'filter_lines - Verify the code to use filters. Verify several example filters' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/before') do
    its(:content) { should match(/line1#{eol}line2#{eol}line3#{eol}HELLO THERE/m) }
    its(:content) { should match(/line1#{eol}line2#{eol}line3#{eol}COMMENT ME/m) }
  end
  describe file_ext('/tmp/before') do
    its('size_lines') { should eq 11 }
  end

  describe file('/tmp/before_first') do
    its(:content) { should match(/line1#{eol}line2#{eol}line3#{eol}HELLO THERE/m) }
    its(:content) { should match(/FOOL#{eol}COMMENT ME/m) }
  end
  describe file_ext('/tmp/before_first') do
    its('size_lines') { should eq 8 }
  end

  describe file('/tmp/before_last') do
    its(:content) { should match(/^HELLO THERE/m) }
    its(:content) { should match(/line1#{eol}line2#{eol}line3#{eol}COMMENT ME/m) }
  end
  describe file_ext('/tmp/before_last') do
    its('size_lines') { should eq 8 }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/Insert lines before match redo.*n/) }
  end
end
