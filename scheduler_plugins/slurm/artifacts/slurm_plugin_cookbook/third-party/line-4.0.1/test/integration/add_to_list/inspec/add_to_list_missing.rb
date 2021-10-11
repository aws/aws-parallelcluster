control 'Add to list missing file' do
  describe file('/tmp/nofilehere') do
    it { should_not exist }
  end

  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/missing_file fail.*n/) }
    its(:content) { should match(/missing_file\]\s*n/) }
  end
end
