title 'Delete lines'

describe file('/tmp/samplefile1') do
  its(:content) { should_not match(/HI THERE I AM DANGERFILE/) }
  its(:content) { should match(/int main/) }
end

describe file('/tmp/samplefile2') do
  its(:content) { should_not match(/# authorized_keys/) }
  its(:content) { should match(/ssh-rsa.*keepme@/) }
  its(:content) { should match(/ssh-dsa/) }
  its(:content) { should match(/ssh-rsa.*keepmetoo/) }
end

describe file('/tmp/samplefile1-regexp') do
  its(:content) { should_not match(/HI THERE I AM DANGERFILE/) }
  its(:content) { should match(/int main/) }
end

describe file('/tmp/samplefile2-regexp') do
  its(:content) { should_not match(/# authorized_keys/) }
  its(:content) { should match(/ssh-rsa.*keepme@/) }
  its(:content) { should match(/ssh-dsa/) }
  its(:content) { should match(/ssh-rsa.*keepmetoo/) }
end

describe file('/tmp/emptyfile') do
  it { should be_file }
  its(:size) { should eq 0 }
end

describe file('/tmp/chef_resource_status') do
  its(:content) { should match(/missing_file fail.*n/) }
  its(:content) { should match(/missing_file\]\s*n/) }
end
