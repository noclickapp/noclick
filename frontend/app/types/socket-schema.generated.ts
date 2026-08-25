// Auto-generated from backend Pydantic models
// DO NOT EDIT MANUALLY - run 'npm run generate:types' instead
// Generated at: Sat Jun 20 14:10:29  2026
// Target: all

/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * Represents a step in an agentic workflow.
 *
 * Used for tracking multi-step AI agent operations with nested sub-steps.
 */
export interface AgenticStep {
  /**
   * Unique identifier for the step
   */
  id: string;
  /**
   * Description of what this step does
   */
  text: string;
  /**
   * Status: pending|in_progress|completed
   */
  status?: string;
  /**
   * Optional nested sub-steps
   */
  sub_steps?: AgenticStep[] | null;
}
/**
 * Single content item in a sequence-sensitive message.
 */
export interface ContentItem {
  type: "text" | "image_url" | "video_url";
  text?: string | null;
  image_url?: string | ImageUrl | null;
  video_url?: string | null;
  /**
   * Optional metadata for the content item (e.g., drawing info, HTML type)
   */
  metadata?: {
    [k: string]: unknown;
  } | null;
}
/**
 * Structured image reference with optional metadata.
 */
export interface ImageUrl {
  url: string;
  detail?: string | null;
  format?: string | null;
}
