class FileExtResource < Inspec.resource(1)
  name 'file_ext'

  desc '
    Check the number of lines in a file
  '

  example "
    describe file_ext('/tmp/output') do
      its('size_lines') { should eq 7 }
    end
  "

  def initialize(path)
    @path = path
    @file = inspec.backend.file(path)
  end

  %w(size_lines).each do |m|
    define_method m.to_sym do |*args|
      file_ext.method(m.to_sym).call(*args)
    end
  end

  def to_s
    "FileExt #{@path}"
  end

  def size_lines
    @file.content ? @file.content.lines.count : 0
  end
end
