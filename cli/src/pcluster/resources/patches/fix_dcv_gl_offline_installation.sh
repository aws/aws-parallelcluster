#!/bin/bash
# Script to patch ParallelCluster AMI for DCV GL offline installation

set -ex

SOURCES_DIR="/opt/parallelcluster/sources"
DCV_GL_DEPS_DIR="${SOURCES_DIR}/dcv-gl-deps"
COOKBOOK_DIR="/etc/chef/cookbooks"
RHEL_COMMON="${COOKBOOK_DIR}/aws-parallelcluster-platform/resources/dcv/partial/_rhel_common.rb"

# Find the nice-dcv-gl RPM
DCV_GL_RPM=$(find "${SOURCES_DIR}" -name "nice-dcv-gl-*.rpm" 2>/dev/null | head -1)
if [[ -z "${DCV_GL_RPM}" ]]; then
    echo "ERROR: nice-dcv-gl RPM not found in ${SOURCES_DIR}"
    exit 1
fi
echo "Found DCV GL package: ${DCV_GL_RPM}"

echo "=== Step 1: Download missing dependencies for nice-dcv-gl ==="
mkdir -p "${DCV_GL_DEPS_DIR}"

# Use dnf to download only packages that would be installed (excludes already installed)
dnf download --destdir="${DCV_GL_DEPS_DIR}" --resolve "${DCV_GL_RPM}" 2>/dev/null || true

# Remove the dcv-gl package itself if downloaded (we only want dependencies)
rm -f "${DCV_GL_DEPS_DIR}"/nice-dcv-gl-*.rpm 2>/dev/null || true

if [[ -n "$(ls -A ${DCV_GL_DEPS_DIR} 2>/dev/null)" ]]; then
    echo "Downloaded dependencies:"
    ls -la "${DCV_GL_DEPS_DIR}"
else
    echo "All dependencies already installed"
fi

echo "=== Step 2: Patch cookbook ==="
cp "${RHEL_COMMON}" "${RHEL_COMMON}.bak"

/opt/cinc/embedded/bin/ruby << 'RUBY_SCRIPT'
file_path = '/etc/chef/cookbooks/aws-parallelcluster-platform/resources/dcv/partial/_rhel_common.rb'
patch_content = <<~'PATCH'
  def install_dcv_gl
    dcv_gl_deps_dir = "#{node['cluster']['sources_dir']}/dcv-gl-deps"
    execute 'install dcv-gl dependencies offline' do
      command "rpm -ivh #{dcv_gl_deps_dir}/*.rpm"
      only_if { ::Dir.exist?(dcv_gl_deps_dir) && !::Dir.empty?(dcv_gl_deps_dir) }
    end

    package = "#{node['cluster']['sources_dir']}/#{dcv_package}/#{dcv_gl}"
    package package do
      action :install
      source package
      options '--disablerepo=*'
    end
  end
PATCH
content = File.read(file_path)
pattern = /^  def install_dcv_gl\n.*?^  end\n/m
if content.match?(pattern)
  File.write(file_path, content.gsub(pattern, patch_content))
  puts "Patched successfully"
else
  abort "ERROR: Could not find install_dcv_gl function"
end
RUBY_SCRIPT

echo "=== Done! Create AMI from this instance ==="