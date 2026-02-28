#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_SPEC="${REPO_ROOT}/apps/api-gateway/openapi/openapi.yaml"
ARTIFACT_SPEC="${REPO_ROOT}/docs/artifacts/openapi-m0-m2.yaml"
SPEC_INPUT="${1:-${RUNTIME_SPEC}}"
if [[ "${SPEC_INPUT}" = /* ]]; then
  SPEC_PATH="${SPEC_INPUT}"
else
  SPEC_PATH="${PWD}/${SPEC_INPUT}"
fi

[[ -f "${SPEC_PATH}" ]] || fail "Spec file not found: ${SPEC_PATH}"
[[ -r "${SPEC_PATH}" ]] || fail "Spec file is not readable: ${SPEC_PATH}"
SPEC_REAL="$(readlink -f "${SPEC_PATH}")"

# Keep runtime and artifact contracts wired together (symlink or identical bytes).
if [[ "${SPEC_REAL}" == "$(readlink -f "${RUNTIME_SPEC}")" ]]; then
  [[ -f "${ARTIFACT_SPEC}" ]] || fail "Artifact spec not found: ${ARTIFACT_SPEC}"
  if [[ -L "${RUNTIME_SPEC}" ]]; then
    runtime_real="$(readlink -f "${SPEC_PATH}")"
    artifact_real="$(readlink -f "${ARTIFACT_SPEC}")"
    [[ "${runtime_real}" == "${artifact_real}" ]] || fail \
      "Runtime spec symlink must resolve to ${ARTIFACT_SPEC}, got ${runtime_real}"
  else
    cmp -s "${SPEC_PATH}" "${ARTIFACT_SPEC}" || fail \
      "Runtime spec must match artifact spec bytes: ${ARTIFACT_SPEC}"
  fi
fi

if command -v redocly >/dev/null 2>&1; then
  echo "Using redocly CLI for OpenAPI validation..."
  redocly lint "${SPEC_PATH}"
  exit 0
fi

if [[ -x "${REPO_ROOT}/node_modules/.bin/redocly" ]]; then
  echo "Using local node_modules redocly CLI for OpenAPI validation..."
  "${REPO_ROOT}/node_modules/.bin/redocly" lint "${SPEC_PATH}"
  exit 0
fi

echo "redocly CLI not found; running offline structural OpenAPI checks..."

ruby - "${SPEC_PATH}" <<'RUBY'
require "yaml"

spec_path = ARGV.fetch(0)

def fail!(message)
  warn("ERROR: #{message}")
  exit(1)
end

def pointer_exists?(root, pointer)
  return true if pointer == "#"
  return false unless pointer.start_with?("#/")

  tokens = pointer[2..].split("/").map { |t| t.gsub("~1", "/").gsub("~0", "~") }
  node = root

  tokens.each do |token|
    case node
    when Hash
      return false unless node.key?(token)
      node = node[token]
    when Array
      return false unless token.match?(/\A\d+\z/)
      idx = token.to_i
      return false if idx >= node.length
      node = node[idx]
    else
      return false
    end
  end

  true
end

def collect_refs(node, path, refs)
  case node
  when Hash
    ref = node["$ref"]
    refs << [path, ref] if ref.is_a?(String)
    node.each { |k, v| collect_refs(v, "#{path}/#{k}", refs) }
  when Array
    node.each_with_index { |v, i| collect_refs(v, "#{path}/#{i}", refs) }
  end
end

begin
  root = YAML.safe_load(File.read(spec_path), aliases: true)
rescue Psych::SyntaxError => e
  fail!("YAML syntax error in #{spec_path}: #{e.message}")
end

fail!("OpenAPI document root must be a mapping/object") unless root.is_a?(Hash)

errors = []

openapi = root["openapi"]
unless openapi.is_a?(String) && openapi.match?(/\A3(?:\.\d+){1,2}\z/)
  errors << "Field 'openapi' must be a 3.x version string"
end

info = root["info"]
unless info.is_a?(Hash) && info["title"].to_s.strip != "" && info["version"].to_s.strip != ""
  errors << "Field 'info.title' and 'info.version' are required and must be non-empty"
end

paths = root["paths"]
unless paths.is_a?(Hash) && !paths.empty?
  errors << "Field 'paths' must be a non-empty object"
end

http_methods = %w[get put post delete options head patch trace]
operation_ids = {}

if paths.is_a?(Hash)
  paths.each do |path_name, path_item|
    errors << "Path key '#{path_name}' must start with '/'" unless path_name.is_a?(String) && path_name.start_with?("/")

    unless path_item.is_a?(Hash)
      errors << "Path item '#{path_name}' must be an object"
      next
    end

    operations = path_item.select { |k, _| http_methods.include?(k) }
    if operations.empty? && !path_item.key?("$ref")
      errors << "Path item '#{path_name}' must define an operation or $ref"
      next
    end

    operations.each do |method, operation|
      op_label = "#{method.upcase} #{path_name}"
      unless operation.is_a?(Hash)
        errors << "Operation #{op_label} must be an object"
        next
      end

      responses = operation["responses"]
      unless responses.is_a?(Hash) && !responses.empty?
        errors << "Operation #{op_label} must define non-empty responses"
      end

      op_id = operation["operationId"]
      next unless op_id

      unless op_id.is_a?(String) && op_id.strip != ""
        errors << "Operation #{op_label} has invalid operationId"
        next
      end

      if operation_ids.key?(op_id)
        errors << "Duplicate operationId '#{op_id}' in #{op_label} and #{operation_ids[op_id]}"
      else
        operation_ids[op_id] = op_label
      end
    end
  end
end

refs = []
collect_refs(root, "#", refs)
refs.each do |location, ref|
  next if pointer_exists?(root, ref)
  next unless ref.start_with?("#")
  errors << "Unresolved local $ref '#{ref}' at #{location}"
end

if errors.any?
  warn("OpenAPI validation failed with #{errors.size} issue(s):")
  errors.each { |err| warn("- #{err}") }
  exit(1)
end

puts("OpenAPI structural checks passed for #{spec_path}")
RUBY
