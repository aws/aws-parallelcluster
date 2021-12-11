control 'Check removed duplicate lines' do
  eol = os.family == 'windows' ? "\r\n" : "\n"

  describe matches('/tmp/no_duplicate_double', /^Remove duplicate lines#{eol}/) do
    its('count') { should eq 1 }
  end
  describe matches('/tmp/no_duplicate_double', /^Identical line#{eol}/) do
    its('count') { should eq 0 }
  end

  describe matches('/tmp/no_duplicate_single', /^Remove duplicate lines#{eol}/) do
    its('count') { should eq 1 }
  end
  describe matches('/tmp/no_duplicate_single', /^Data line#{eol}/) do
    its('count') { should eq 0 }
  end
  describe matches('/tmp/no_duplicate_single', /^Identical line#{eol}/) do
    its('count') { should eq 2 }
  end

  describe matches('/tmp/no_duplicate_exists', /^Remove duplicate lines#{eol}/) do
    its('count') { should eq 1 }
  end
  describe matches('/tmp/no_duplicate_exists', /\ARemove duplicate lines#{eol}/) do
    its('count') { should eq 1 }
  end
  describe matches('/tmp/no_duplicate_exists', /^Identical line#{eol}/) do
    its('count') { should eq 0 }
  end

  describe matches('/tmp/no_duplicate_replace_only', /^Remove duplicate lines#{eol}/) do
    its('count') { should eq 1 }
  end
  describe matches('/tmp/no_duplicate_replace_only', /^Identical line#{eol}/) do
    its('count') { should eq 0 }
  end

  # redo of resource did nothing
  describe file('/tmp/chef_resource_status') do
    its(:content) { should match(/duplicate redo.*n#{eol}/) }
  end
end
