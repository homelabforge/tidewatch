/**
 * @name TideWatch Custom Sanitizers
 * @description Defines custom sanitization functions used in TideWatch
 * @kind path-problem
 */

import python
import semmle.python.security.dataflow.LogInjectionCustomizations

/**
 * A sanitizer for log injection that recognizes our custom sanitize_log_message function
 */
class TideWatchLogSanitizer extends LogInjection::Sanitizer {
  TideWatchLogSanitizer() {
    exists(CallNode call |
      call.getFunction().(AttrNode).getName() = "sanitize_log_message" or
      call.getFunction().(NameNode).getId() = "sanitize_log_message"
    |
      this.asCfgNode() = call
    )
  }
}
