#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "time"

TOOL_NAME_MAP = {
  # Claude Code tool names
  "Bash"      => "bash",
  "Read"      => "read",
  "Write"     => "write",
  "Edit"      => "edit",
  "Glob"      => "glob",
  "Grep"      => "grep",
  "WebSearch" => "web_search",
  "WebFetch"  => "web_fetch",
  # Codex item types
  "command_execution" => "bash",
  "file_change"       => "file_change",
  "mcp_tool_call"     => "mcp",
  "web_search"        => "web_search",
  "todo_list"         => "todo_list",
}.freeze

CODEX_TOOL_ITEM_TYPES = %w[command_execution file_change mcp_tool_call web_search todo_list].freeze

def normalize_tool_name(name)
  TOOL_NAME_MAP[name] || name.to_s.downcase
end

def emit(event)
  event["ts"] ||= Time.now.utc.iso8601(3)
  $stdout.puts(JSON.generate(event))
  $stdout.flush
end

# --- Claude Code Normalizer ---

class ClaudeCodeNormalizer
  def initialize
    @turn_index = -1
    @session_started = false
    @session_id = nil
    @model = nil
    @blocks = {}          # index -> {type:, text:, tool_use_id:, tool:, input_json:}
    @stop_reason = nil
    @usage = nil
    @message_id = nil
  end

  def process(raw)
    type = raw["type"]
    return if type == "ping"

    case type
    when "system"
      handle_system(raw)
    when "message_start"
      handle_message_start(raw)
    when "content_block_start"
      handle_content_block_start(raw)
    when "content_block_delta"
      handle_content_block_delta(raw)
    when "content_block_stop"
      handle_content_block_stop(raw)
    when "message_delta"
      handle_message_delta(raw)
    when "message_stop"
      handle_message_stop(raw)
    end
  end

  def finalize
    emit({ "type" => "session.end", "source" => "claude", "status" => "completed" })
  end

  private

  def handle_system(raw)
    return if @session_started
    subtype = raw.dig("subtype")
    return unless subtype == "init"
    @session_started = true
    @session_id = raw.dig("session_id")
    emit({ "type" => "session.start", "source" => "claude", "session_id" => @session_id, "model" => nil })
  end

  def handle_message_start(raw)
    msg = raw.dig("message") || {}
    @turn_index += 1
    @message_id = msg["id"]
    @model ||= msg["model"]
    @blocks = {}
    @stop_reason = nil
    @usage = nil

    unless @session_started
      @session_started = true
      emit({ "type" => "session.start", "source" => "claude", "session_id" => @session_id, "model" => @model })
    end

    emit({ "type" => "turn.start", "source" => "claude", "turn_index" => @turn_index, "message_id" => @message_id })
  end

  def handle_content_block_start(raw)
    idx = raw["index"]
    cb = raw["content_block"] || {}
    block_type = cb["type"]

    block = { "type" => block_type, "text" => String.new, "input_json" => String.new }

    if block_type == "tool_use"
      block["tool_use_id"] = cb["id"]
      block["tool"] = cb["name"]
      emit({
        "type" => "tool.start", "source" => "claude",
        "turn_index" => @turn_index,
        "tool_use_id" => cb["id"],
        "tool" => normalize_tool_name(cb["name"]),
        "input" => {}
      })
    end

    @blocks[idx] = block
  end

  def handle_content_block_delta(raw)
    idx = raw["index"]
    delta = raw["delta"] || {}
    block = @blocks[idx]
    return unless block

    case delta["type"]
    when "text_delta"
      block["text"] << (delta["text"] || "")
      emit({
        "type" => "message.delta", "source" => "claude",
        "turn_index" => @turn_index,
        "text" => delta["text"] || ""
      })
    when "thinking_delta"
      block["text"] << (delta["thinking"] || "")
      emit({
        "type" => "thinking.delta", "source" => "claude",
        "turn_index" => @turn_index,
        "text" => delta["thinking"] || ""
      })
    when "input_json_delta"
      block["input_json"] << (delta["partial_json"] || "")
      emit({
        "type" => "tool.delta", "source" => "claude",
        "turn_index" => @turn_index,
        "tool_use_id" => block["tool_use_id"],
        "partial_json" => delta["partial_json"] || ""
      })
    end
  end

  def handle_content_block_stop(raw)
    idx = raw["index"]
    block = @blocks.delete(idx)
    return unless block

    case block["type"]
    when "text"
      emit({
        "type" => "message", "source" => "claude",
        "turn_index" => @turn_index,
        "text" => block["text"]
      })
    when "thinking"
      emit({
        "type" => "thinking", "source" => "claude",
        "turn_index" => @turn_index,
        "text" => block["text"]
      })
    when "tool_use"
      input = begin
        JSON.parse(block["input_json"])
      rescue
        {}
      end
      emit({
        "type" => "tool.end", "source" => "claude",
        "turn_index" => @turn_index,
        "tool_use_id" => block["tool_use_id"],
        "tool" => normalize_tool_name(block["tool"]),
        "input" => input
      })
    end
  end

  def handle_message_delta(raw)
    delta = raw["delta"] || {}
    @stop_reason = delta["stop_reason"]
    @usage = raw["usage"]
  end

  def handle_message_stop(_raw)
    emit({
      "type" => "turn.end", "source" => "claude",
      "turn_index" => @turn_index,
      "status" => "completed",
      "stop_reason" => @stop_reason,
      "usage" => @usage
    })
  end
end

# --- Codex Normalizer ---

class CodexNormalizer
  def initialize
    @turn_index = -1
    @session_id = nil
  end

  def process(raw)
    type = raw["type"]

    case type
    when "thread.started"
      @session_id = raw["thread_id"]
      emit({ "type" => "session.start", "source" => "codex", "session_id" => @session_id, "model" => raw["model"] })
    when "turn.started"
      @turn_index += 1
      emit({ "type" => "turn.start", "source" => "codex", "turn_index" => @turn_index, "message_id" => raw["message_id"] })
    when "turn.completed"
      emit({
        "type" => "turn.end", "source" => "codex",
        "turn_index" => @turn_index,
        "status" => "completed",
        "stop_reason" => raw["stop_reason"],
        "usage" => raw["usage"]
      })
    when "turn.failed"
      emit({
        "type" => "turn.end", "source" => "codex",
        "turn_index" => @turn_index,
        "status" => "failed",
        "stop_reason" => nil,
        "usage" => nil
      })
      emit({ "type" => "error", "source" => "codex", "message" => raw["error"] || "turn failed" })
    when "item.started"
      handle_item_started(raw)
    when "item.completed"
      handle_item_completed(raw)
    when "agent_message.content.delta"
      emit({ "type" => "message.delta", "source" => "codex", "turn_index" => @turn_index, "text" => raw["delta"] || "" })
    when "reasoning.content.delta"
      emit({ "type" => "thinking.delta", "source" => "codex", "turn_index" => @turn_index, "text" => raw["delta"] || "" })
    when "error"
      emit({ "type" => "error", "source" => "codex", "message" => raw["message"] || raw["error"] || "unknown error" })
    end
  end

  def finalize
    emit({ "type" => "session.end", "source" => "codex", "status" => "completed" })
  end

  private

  def handle_item_started(raw)
    item_type = raw["item_type"] || raw.dig("item", "type")
    return unless CODEX_TOOL_ITEM_TYPES.include?(item_type)

    emit({
      "type" => "tool.start", "source" => "codex",
      "turn_index" => @turn_index,
      "tool_use_id" => raw["item_id"] || raw.dig("item", "id") || "",
      "tool" => normalize_tool_name(item_type),
      "input" => raw.dig("item", "input") || raw["input"] || {}
    })
  end

  def handle_item_completed(raw)
    item = raw["item"] || raw
    item_type = item["type"]

    case item_type
    when "agent_message"
      text = extract_text(item)
      emit({ "type" => "message", "source" => "codex", "turn_index" => @turn_index, "text" => text })
    when "reasoning"
      text = extract_text(item)
      emit({ "type" => "thinking", "source" => "codex", "turn_index" => @turn_index, "text" => text })
    else
      if CODEX_TOOL_ITEM_TYPES.include?(item_type)
        emit({
          "type" => "tool.end", "source" => "codex",
          "turn_index" => @turn_index,
          "tool_use_id" => item["id"] || "",
          "tool" => normalize_tool_name(item_type),
          "input" => item["input"] || {}
        })
      end
    end
  end

  def extract_text(item)
    content = item["content"]
    return content if content.is_a?(String)
    return content.map { |c| c["text"] || "" }.join if content.is_a?(Array)
    ""
  end
end

# --- Main ---

def detect_source(line_data)
  type = line_data["type"].to_s
  return :claude if type.include?("message_start") || type.include?("content_block") || type == "ping" || type == "system" || type == "message_delta" || type == "message_stop"
  return :codex if type.start_with?("thread.") || type.start_with?("turn.") || type.start_with?("item.") || type.include?("delta") || type == "error"
  # Fallback: check for stream_event key
  return :claude if line_data.key?("stream_event")
  nil
end

normalizer = nil

$stdin.each_line do |line|
  line = line.strip
  next if line.empty?

  begin
    data = JSON.parse(line)
  rescue JSON::ParserError
    next
  end

  if normalizer.nil?
    source = detect_source(data)
    normalizer = case source
                 when :claude then ClaudeCodeNormalizer.new
                 when :codex  then CodexNormalizer.new
                 else
                   $stderr.puts "Unable to detect source from first event: #{data["type"]}"
                   exit 1
                 end
  end

  normalizer.process(data)
end

normalizer&.finalize
