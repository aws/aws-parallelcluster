Dir.glob('libraries/*.rb').each do |lib|
  require_relative "../#{lib}"
end

require 'berkshelf'
require 'chefspec'
require 'chefspec/berkshelf'

RSpec.configure do |config|
  config.expose_dsl_globally = true
  config.mock_with :rspec do |mocks|
    mocks.allow_message_expectations_on_nil = true
  end
end
