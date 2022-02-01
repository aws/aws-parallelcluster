# Chef Handler for reporting resource status to a file
#
# Based on chef-handler-elapsed-time by James Casey
#
class Chef
  class Handler
    class ResourceStatus < Chef::Handler
      def initialize(file = '/tmp/resource_status')
        @config = {}
        @config[:file] ||= file
      end

      def report
        f = ::File.open(@config[:file], 'wb')
        all_resources.each do |r|
          f.puts "#{full_name(r)} #{updated(r)}"
        end
        f.close
      end

      private

      def updated(resource)
        resource.updated ? 'y' : 'n'
      end

      def full_name(resource)
        "#{resource.resource_name}[#{resource.name}]"
      end
    end
  end
end
