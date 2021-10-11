class MatchResource < Inspec.resource(1)
  name 'matches'

  desc '
    Check the number of occurances of a match in a file
  '

  example "
    describe matches('/tmp/output', /^$/) do
      its('count') { should eq 1 }
    end
  "

  def initialize(path, pattern)
    @path = path
    @pattern = pattern
    @file = inspec.backend.file(path)
  end

  %w(count).each do |m|
    define_method m.to_sym do |*args|
      matches.method(m.to_sym).call(*args)
    end
  end

  def to_s
    "Matches #{@path} #{@pattern}"
  end

  def count
    @file.exist? ? @file.content.scan(@pattern).size : 0
  end
end
