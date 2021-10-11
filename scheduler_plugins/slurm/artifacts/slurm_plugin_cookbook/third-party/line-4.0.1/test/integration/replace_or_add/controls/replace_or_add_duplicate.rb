control 'Change multiple lines with one pass' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe matches('/tmp/duplicate', /^Replace duplicate lines#{eol}/) do
    its('count') { should eq 2 }
  end
  describe matches('/tmp/duplicate', /^Identical line#{eol}/) do
    its('count') { should eq 0 }
  end

  describe matches('/tmp/duplicate_replace_only', /^Replace duplicate lines#{eol}/) do
    its('count') { should eq 2 }
  end
  describe matches('/tmp/duplicate_replace_only', /^Identical line#{eol}/) do
    its('count') { should eq 0 }
  end

  # redo of resource did nothing
  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/duplicate redo.*n#{eol}/) }
  end
end
