title 'Delete from list'
eol = os.family == 'windows' ? "\r\n" : "\n"

describe file('/tmp/samplefile3') do
  its(:content) { should_not match(/192\.168\.0\.0/) }
  its(:content) { should_not match(/10\.0\.0\.0/) }
  its(:content) { should match(/172\.16\.0\.0/) }
end

describe file('/tmp/samplefile3') do
  its(:content) { should_not match(/425/) }
end

describe file('/tmp/samplefile3') do
  its(:content) { should_not match(/Joe/) }
  its(:content) { should_not match(/Karen/) }
  its(:content) { should match(/People to call: Bobby/) }
end

control 'File should still contain' do
  describe file('/tmp/samplefile3') do
    its(:content) { should match(/last_delimited_list= \(\|single\|\)/) }
  end
end

describe file('/tmp/samplefile3') do
  its(:content) { should match(/reported#{eol}/) }
  its(:content) { should match(/altform#{eol}/) }
  its(:content) { should match(/double  space  entry  fin#{eol}/) }
  its(:content) { should match(/^list, comma-space, fourth#{eol}/) }
  its(:content) { should match(/^list ,space-comma ,fourth#{eol}/) }
  its(:content) { should match(/^last line#{eol}/) }
end

describe file('/tmp/emptyfile') do
  it { should exist }
  its(:size) { should eq 0 }
end

describe file('/tmp/ends_with_test_last_entry') do
  its(:content) { should match(%r{GRUB_CMDLINE_LINUX=\"rd.lvm.lv=centos/root rd.lvm quiet\"}) }
end

describe file('/tmp/ends_with_test_middle_entry') do
  its(:content) { should match(%r{GRUB_CMDLINE_LINUX=\"rd.lvm.lv=centos/root quiet elevator=noop\"}) }
end

describe file('/tmp/chef_resource_status') do
  its(:content) { should match(/missing_file fail.*n#{eol}/) }
  its(:content) { should match(/missing_file\]\s*n#{eol}/) }
end
