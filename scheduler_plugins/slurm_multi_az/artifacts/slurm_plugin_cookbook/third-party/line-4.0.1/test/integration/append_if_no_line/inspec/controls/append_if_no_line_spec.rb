control 'Append lines' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe file('/tmp/samplefile') do
    its(:content) { should match(/HI THERE I AM STRING#{eol}/) }
  end

  describe matches('/tmp/samplefile', 'HI THERE I AM STRING') do
    its(:count) { should eq 1 }
  end

  describe matches('/tmp/samplefile', 'AM I A STRING?+\'".*/-\(){}^$[]') do
    its(:count) { should eq 1 }
  end

  describe file_ext('/tmp/samplefile') do
    its(:size_lines) { should eq 7 }
  end

  describe file('/tmp/file_without_linereturn') do
    its(:content) { should eql("no carriage return line#{eol}SHOULD GO ON ITS OWN LINE#{eol}") }
  end

  describe file('/tmp/add_emptyfile') do
    its(:content) { should eql("added line#{eol}") }
  end

  # The last line has an eol
  describe file('/tmp/samplefile') do
    its(:content) { should match(/^last line#{eol}/) }
  end

  # Create a missing file if ignore missing is specified
  describe file('/tmp/add_missing') do
    its(:content) { should match(/^added line#{eol}/) }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/missing_file fail.*n/) }
    its(:content) { should match(/missing_file\]\s*y/) }
  end
end
