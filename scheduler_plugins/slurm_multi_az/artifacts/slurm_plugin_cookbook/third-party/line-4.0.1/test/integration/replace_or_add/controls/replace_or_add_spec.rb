control 'Replace or add lines' do
  eol = os.family == 'windows' ? "\r\n" : "\n"
  describe file('/tmp/samplefile') do
    its(:content) { should match(/hey there how you doin/) }
  end

  describe file('/tmp/samplefile2') do
    its(:content) { should_not match(/ssh-dsa/) }
    its(:content) { should match(/ssh-rsa change 2/) }
    its(:content) { should match(/^last line#{eol}/) }
  end

  describe file('/tmp/emptyfile') do
    its(:size) { should eq 0 }
  end
end
